"""
HL7 Message Processor Actor — Phase 15/16

Dramatiq actor que procesa mensajes HL7 del Ozelle en background.
Decouple la recepción TCP del procesamiento pesado del Core.
"""

import dramatiq
import logfire
import anyio
import redis
import re
import uuid

from sqlmodel import Session, create_engine
from app.database import AsyncSessionLocal
from app.domains.reception.schemas import RawPatientInput, PatientSource
from app.domains.taller.schemas import EnrichRequest, ImageUploadRequest
from app.satellites.ozelle.hl7_parser import parse_hl7_message, HL7ParsingError, HeartbeatMessageException, ParsedOzelleMessage
# from app.domains.reception.service import ReceptionService # Moved to inside function
from app.domains.taller.service import TallerService # Moved to inside function
from app.config import settings # Import settings



# ── Module-level service instances (shared across actor invocations) ────────────


def _reception_service() -> "ReceptionService":
    from app.domains.reception.service import ReceptionService # Local import to break circular dependency
    return ReceptionService()


def _taller_service() -> "TallerService":
    from app.domains.taller.service import TallerService # Local import to break circular dependency
    return TallerService()

# Synchronous engine for Dramatiq actor's DB operations
sync_engine = create_engine(settings.DATABASE_URL, echo=False)


# ── Dramatiq Actor ─────────────────────────────────────────────────────────────

def set_upload_status(upload_id: str, status: str, count: int = 0) -> None:
    """Write upload status to Redis. Status: 'processing', 'complete:{n}', 'error:{msg}'"""
    r = redis.from_url(settings.REDIS_URL)
    if status == "processing":
        r.setex(f"upload:{upload_id}:status", 300, status)  # 5 minutes TTL
    elif status.startswith("complete:"):
        r.setex(f"upload:{upload_id}:status", 300, f"{status}{count}")  # 5 minutes TTL
    elif status.startswith("error:"):
        r.setex(f"upload:{upload_id}:status", 300, status)  # 5 minutes TTL
    logfire.info(f"Upload status for {upload_id} set to {status}")

def get_upload_status(upload_id: str) -> str | None:
    """Read upload status from Redis. Returns None if not found."""
    r = redis.from_url(settings.REDIS_URL)
    status = r.get(f"upload:{upload_id}:status")
    if status:
        return status.decode('utf-8')
    return None

@dramatiq.actor(max_retries=3, time_limit=60000)
def process_hl7_message(raw_hl7: str, source: str):
    """
    Dramatiq actor to process an incoming HL7 message.
    Retries up to 3 times on failure with exponential backoff.
    """
    logfire.info(f"Procesando mensaje HL7 en background (fuente: {source})")
    try:
        logfire.info(f"Processing HL7 message from source: {source}")
        logfire.debug(f"Raw message length: {len(raw_hl7)} characters")
        
        parsed = parse_hl7_message(raw_hl7, source)
        logfire.info(
            f"Mensaje parseado correctamente: {parsed.test_type_name} "
            f"para '{parsed.raw_patient_string}'"
        )

        # Async execution wrapper
        anyio.run(_async_process_pipeline, parsed, source)

    except (HL7ParsingError, HeartbeatMessageException) as e:
        # Fatal errors: malformed message or heartbeat. Neither should retry.
        logfire.error(f"Error fatal procesando HL7. Se descarta. {e}")
        logfire.debug(f"Failed message content (first 500 chars): {raw_hl7[:500]}")
        # Not raising so it doesn't trigger Dramatiq retry
    except Exception as e:
        logfire.error(f"Error procesando mensaje. Se reintentará. Error: {e}")
        logfire.debug(f"Failed message content (first 500 chars): {raw_hl7[:500]}")
        raise  # Raise to trigger Dramatiq retry


# ── Pipeline ───────────────────────────────────────────────────────────────────


async def _async_process_pipeline(parsed_msg: ParsedOzelleMessage, source: str):
    """
    The actual async pipeline that connects the Satellite to the Core.

    1. Send raw patient string to Reception (normalize + deduplicate → Baúl)
    2. Send lab values to Taller (Enrichment: create TestResult + flag values)
    3. Send images to Taller (Image Storage)
    """

    logfire.info(f"Iniciando pipeline para paciente: '{parsed_msg.raw_patient_string}'")

    source_enum = PatientSource(source)
    # 1. Prepare Reception Input
    # Pasar especie/sexo extraídos del HL7 (PID[10]/PID[8]) para que el normalizador
    # los use en lugar de "Desconocida" cuando el paciente tiene código corto.
    reception_input = RawPatientInput(
        raw_string=parsed_msg.raw_patient_string,
        session_code=parsed_msg.sample_id,
        source=source_enum,
        received_at=parsed_msg.received_at,
        species_override=parsed_msg.species,
        sex_override=parsed_msg.sex,
    )

    async with AsyncSessionLocal() as session:
        try:
            # ── RECEPTION PHASE ──────────────────────────────────────────────
            logfire.debug("Llamando a ReceptionService...")
            baul_result = await _reception_service().receive(reception_input, session)
            patient_id = baul_result.patient_id
            normalized_patient = baul_result.patient

            logfire.info(
                f"Recepción completada. Paciente ID: {patient_id} "
                f"(Nuevo: {baul_result.created})"
            )

            # ── TALLER PHASE — Enrichment ────────────────────────────────────
            logfire.debug("Llamando a TallerService (Enrichment)...")

            # Create TestResult
            tr = await _taller_service().create_test_result(
                patient_id=patient_id,
                test_type=parsed_msg.test_type_name,
                test_type_code=parsed_msg.test_type_code,
                source=source,
                received_at=parsed_msg.received_at,
                session=session,
            )

            # Flag + store lab values
            flag_result = await _taller_service().flag_and_store(
                test_result_id=tr.id,
                species=normalized_patient.species,
                values=parsed_msg.lab_values,
                session=session,
            )

            logfire.info(
                f"Taller Enrichment completado. TestResult ID: {tr.id}. "
                f"Resumen: {flag_result.summary}"
            )

            # ── TALLER PHASE — Images ─────────────────────────────────────────
            if parsed_msg.images:
                logfire.debug(f"Procesando {len(parsed_msg.images)} imágenes...")
                image_req = ImageUploadRequest(
                    test_result_id=tr.id,
                    patient_name=normalized_patient.name,
                    owner_name=normalized_patient.owner_name,
                    received_at=parsed_msg.received_at,
                    images=parsed_msg.images,
                )

                img_result = await _taller_service().save_images(image_req, session)
                logfire.info(
                    f"Imágenes guardadas: {img_result.total_saved} "
                    f"(Fallaron: {img_result.total_failed})"
                )
            else:
                logfire.info("El mensaje no contiene imágenes.")

            logfire.info("Pipeline completado exitosamente.")

        except Exception as e:
            logfire.error(f"Error crítico en pipeline asíncrono: {e}")
            # Re-raise so the Dramatiq actor knows it failed and can retry
            raise


def split_hl7_batch(batch_content: str) -> list[str]:
    # Find all occurrences of "MSH|"
    starts = [m.start() for m in re.finditer(r'MSH\|', batch_content)]
    
    messages = []
    for i in range(len(starts)):
        start_index = starts[i]
        # End of message is either the start of the next MSH or end of file
        end_index = starts[i+1] if i+1 < len(starts) else len(batch_content)
        
        message = batch_content[start_index:end_index].strip()
        if message: # Only add non-empty messages
            messages.append(message)
    return messages

@dramatiq.actor(max_retries=3, time_limit=300000)
def process_uploaded_batch(file_content: str, file_type: str, upload_id: str) -> None:
    """Process a batch HL7 file upload. Splits multi-message content, filters heartbeats,
    parses each message, and saves patients to DB."""
    
    logfire.info(f"Starting batch upload processing for upload_id: {upload_id}, file_type: {file_type}")
    
    parsed_message_count = 0
    
    try:
        messages = split_hl7_batch(file_content)
        
        logfire.info(f"Split batch file into {len(messages)} potential HL7 messages.")
        
        for i, msg_str in enumerate(messages):
            if not msg_str:
                continue

            try:
                if file_type == "ozelle":
                    # Filter heartbeats: skip messages where MSH-9 contains ZHB^H00
                    # The ozelle parser already raises HeartbeatMessageException
                    # for heartbeats, so we can catch that.
                    
                    # Create own DB session (NOT from request context)
                    # This is actually handled by _async_process_pipeline, but for the parsing part,
                    # we still need to catch exceptions.
                    
                    # The existing process_hl7_message actor expects a raw HL7 string
                    # and the source. The source will be Ozelle for this file type.
                    
                    # Call parse_hl7_message() from app.satellites.ozelle.hl7_parser
                    # This parsing happens inside process_hl7_message actor.
                    # Here we just pass the raw message string.
                    
                    # We can't directly call parse_hl7_message here to filter heartbeats
                    # because it requires a source. It's better to let the process_hl7_message
                    # actor handle the parsing and HeartbeatMessageException.
                    
                    # The instruction says "Filter heartbeats: skip messages where MSH-9 contains ZHB^H00"
                    # and "Handle HeartbeatMessageException — just skip that message"
                    # This implies we should parse here to skip heartbeats BEFORE sending to the actor.
                    
                    # Let's try to parse it here to filter heartbeats.
                    # The parse_hl7_message function needs the source.
                    
                    # For filtering heartbeats in the batch processor, we need to examine MSH-9
                    # without fully parsing it.
                    # A quick regex check for MSH-9 segment for heartbeat.
                    # MSH|^~\&|...|...|...|...|...|...|ZHB^H00...
                    if "MSH|" in msg_str and "ZHB^H00" in msg_str.split("|")[8 if len(msg_str.split("|")) > 8 else 0]:
                        logfire.info(f"Skipping heartbeat message {i+1}/{len(messages)} for upload_id: {upload_id}")
                        continue

                    # If not a heartbeat, send for processing
                    process_hl7_message.send(msg_str, PatientSource.LIS_OZELLE.value)
                    parsed_message_count += 1
                    
                elif file_type == "fujifilm":
                    # Call appropriate fujifilm parser (placeholder for now)
                    # For now, if fujifilm is selected, it will just send it to the existing fujifilm processor
                    # which expects a single message.
                    from app.tasks.fujifilm_processor import process_fujifilm_message
                    process_fujifilm_message.send(msg_str) # Assuming fujifilm can handle single HL7 message.
                    parsed_message_count += 1
                else:
                    logfire.warning(f"Unsupported file_type '{file_type}' for message {i+1}/{len(messages)} in upload_id: {upload_id}")
                    continue
            except Exception as e:
                logfire.error(f"Error processing individual message {i+1}/{len(messages)} for upload_id: {upload_id}: {e}")
                # Continue processing other messages in the batch even if one fails
                continue
                
        set_upload_status(upload_id, "complete:", parsed_message_count)
        logfire.info(f"Finished batch upload processing for upload_id: {upload_id}. Processed {parsed_message_count} messages.")
        
    except Exception as e:
        logfire.error(f"Critical error during batch upload processing for upload_id: {upload_id}: {e}")
        set_upload_status(upload_id, f"error:{e}")
        # Don't re-raise, the status is already set to error.


# ── Pipeline ───────────────────────────────────────────────────────────────────
