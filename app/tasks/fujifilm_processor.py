"""
Fujifilm Message Processor Actor — handles Fujifilm NX600 chemistry readings.

Decouples TCP reception from Core processing via Dramatiq background tasks.
Similar to hl7_processor.py but tailored for Fujifilm-format messages.
"""

import logging
import sys

import dramatiq
import logfire
import anyio
from datetime import datetime, timedelta, timezone

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

from app.database import AsyncSessionLocal
from sqlalchemy.ext.asyncio import AsyncSession
from app.domains.reception.schemas import RawPatientInput, PatientSource
from app.domains.reception.service import ReceptionService

# NEW IMPORTS FOR FUJIFILM PROCESSING
from clinical_standards import VETERINARY_STANDARDS, get_parameter_name
from app.core.reference import get_reference_range
from app.domains.taller.service import TallerService
from app.domains.taller.schemas import RawLabValueInput
from app.domains.patients.models import Patient
from app.shared.models.test_result import TestResult
from app.shared.models.lab_value import LabValue
from sqlmodel import select


# ── Module-level service instances (shared across actor invocations) ─────────


def _reception_service() -> ReceptionService:
    """Provide a ReceptionService instance for this actor invocation."""
    return ReceptionService()


def _taller_service() -> TallerService:
    """Provide a TallerService instance for this actor invocation."""
    return TallerService()


# ── Dramatiq Actor ───────────────────────────────────────────────────────────


@dramatiq.actor(max_retries=3, time_limit=60000)
def process_fujifilm_message(data: dict):
    """
    Process a Fujifilm chemistry reading via ReceptionService.

    Expected data keys:
      - internal_id: str        # e.g. "908"
      - patient_name: str       # e.g. "POLO"
      - parameter_code: str     # e.g. "CRE" (optional — may be omitted for stub registration)
      - raw_value: str          # e.g. "0.87" (optional)
      - source: str             # PatientSource value (defaults to LIS_FUJIFILM)
      - received_at: str        # ISO timestamp (optional — defaults to now)

    Retries up to 3 times on failure with exponential backoff.
    """
    source_value = data.get("source", PatientSource.LIS_FUJIFILM.value)
    internal_id = data.get("internal_id", "")
    patient_name = data.get("patient_name", "")
    parameter_code = data.get("parameter_code", "")
    raw_value = data.get("raw_value", "")
    if raw_value == "****":
        raw_value = None

    logger.info(
        f"Processing Fujifilm reading: patient={patient_name}, internal_id={internal_id}, "
        f"param={parameter_code}, value={raw_value}, source={source_value}"
    )
    logfire.info(
        "Processing Fujifilm reading",
        patient_name=patient_name,
        internal_id=internal_id,
        parameter=parameter_code,
        value=raw_value,
        source=source_value,
    )

    try:
        # Build raw string for ReceptionService normalization.
        # For Fujifilm we only have the patient name from the analyzer
        # (the machine doesn't provide owner/species/age).
        raw_string = patient_name.strip()
        if not raw_string:
            logfire.warning("Fujifilm: empty patient_name — nothing to process")
            return

        received_at_str = data.get("received_at")
        if received_at_str:
            try:
                received_at = datetime.fromisoformat(received_at_str.replace("Z", "+00:00"))
                if received_at.tzinfo is None:
                    received_at = received_at.replace(tzinfo=timezone.utc)
            except Exception:
                logfire.warning(f"Fujifilm: invalid received_at '{received_at_str}', using now()")
                received_at = datetime.now(timezone.utc)
        else:
            received_at = datetime.now(timezone.utc)

        reception_input = RawPatientInput(
            raw_string=raw_string,
            session_code=None,
            source=PatientSource(source_value),
            received_at=received_at,
        )

        # Async execution of the Core pipeline
        anyio.run(_async_process_pipeline, reception_input, internal_id, parameter_code, raw_value)

    except Exception as e:
        logger.error(f"Fujifilm processing failed: {e}", exc_info=True)
        logfire.error(f"Fujifilm processing failed: {e}", exc_info=True)
        raise  # Trigger Dramatiq retry


# ── Merge Helper ─────────────────────────────────────────────────────────────


async def _find_or_create_test_result(
    taller_svc: TallerService,
    patient_id: int,
    source: str,
    received_at: datetime,
    session: AsyncSession,
) -> TestResult:
    """Find existing TestResult by (patient_id, source) within a time window or create new.

    Uses a ±3-second window on received_at instead of exact match to handle
    both file uploads (same timestamp) and live TCP adapter (timestamps may
    differ by milliseconds when the machine sends each parameter as a separate
    TCP line). All readings from the same transmission are grouped into a
    single TestResult.
    """
    window = timedelta(seconds=3)
    result = await session.execute(
        select(TestResult).where(
            TestResult.patient_id == patient_id,
            TestResult.source == source,
            TestResult.received_at.between(
                received_at - window,
                received_at + window,
            ),
        ).order_by(TestResult.received_at.desc())
    )
    existing = result.scalars().first()
    if existing:
        logger.info(f"Found existing TestResult {existing.id} for patient {patient_id} (time window match)")
        logfire.info(f"Found existing TestResult {existing.id} for patient {patient_id} (time window match)")
        return existing

    return await taller_svc.create_test_result(
        patient_id=patient_id,
        test_type="Química Sanguínea",
        test_type_code="CHEM",
        source=source,
        received_at=received_at,
        session=session,
    )


# ── Pipeline ─────────────────────────────────────────────────────────────────


async def _async_process_pipeline(
    reception_input: RawPatientInput,
    internal_id: str,
    parameter_code: str,
    raw_value: str | None,
):
    """
    Fujifilm processing pipeline:

    1. Call ReceptionService with the patient name.
       - Normalization will attempt to extract species/age/owner from the name string.
       - If the name is not parseable it still produces a valid NormalizedPatient
         (species/heuristics may default).
    2. Register in Baúl (deduplication + patient creation).

    Note: Fujifilm data is inherently simpler than HL7: one value at a time.
    We forward it through ReceptionService so it appears in the Baúl just like
    other sources, making it queryable and deduplicated.
    """
    logger.info(
        f"Fujifilm pipeline starting: patient={reception_input.raw_string}, "
        f"internal_id={internal_id}, param={parameter_code}"
    )
    logfire.info(
        "Fujifilm pipeline starting",
        patient_name=reception_input.raw_string,
        internal_id=internal_id,
        parameter=parameter_code,
    )

    try:
        async with AsyncSessionLocal() as session:
            service = _reception_service()

            # ── RECEPTION PHASE ─────────────────────────────────────────────
            baul_result = await service.receive(reception_input, session)
            patient_id = baul_result.patient_id
            normalized_patient = baul_result.patient

            logger.info(
                f"Fujifilm reception complete: patient_id={patient_id}, "
                f"created={baul_result.created}, name={normalized_patient.name}"
            )
            logfire.info(
                f"Fujifilm recepción completada. Paciente ID: {patient_id} "
                f"(nuevo: {baul_result.created}) — name: {normalized_patient.name}"
            )

            # ── Record the chemistry value as a note / future TestResult ───────
            # Currently we don't push Fujifilm values into the taller/lab pipeline
            # because they lack species-specific reference ranges and full context.
            # They are recorded via the Baúl for patient history and can be
            # processed later when integrated with the full test-result schema.
            # (The HL7 path handles full lab integration via TallerService.)

            if parameter_code and raw_value is not None:
                logger.info(
                    f"Fujifilm chemistry reading now fully processing: "
                    f"patient_id={patient_id}, param={parameter_code}, value={raw_value}"
                )
                logfire.info(
                    f"Fujifilm chemistry reading now fully processing",
                    patient_id=patient_id,
                    parameter=parameter_code,
                    value=raw_value,
                )

                # 1. Obtener info del parámetro desde clinical_standards
                param_info = VETERINARY_STANDARDS.get(parameter_code, {})
                param_name_es = get_parameter_name(parameter_code, short=False)
                param_unit = param_info.get("unit", "")

                # 2. Parsear raw_value
                try:
                    numeric_value = float(raw_value)
                except (ValueError, TypeError):
                    numeric_value = None

                # 3. Use the already obtained normalized_patient
                
                # 4. Find or create TestResult (merge: same patient+source+received_at → same TR)
                taller_svc = _taller_service()
                
                tr = await _find_or_create_test_result(
                    taller_svc=taller_svc,
                    patient_id=patient_id,
                    source="LIS_FUJIFILM",
                    received_at=reception_input.received_at,
                    session=session,
                )

                # 5. Check for duplicate parameter_code in this TestResult
                dup_result = await session.execute(
                    select(LabValue).where(
                        LabValue.test_result_id == tr.id,
                        LabValue.parameter_code == parameter_code,
                    )
                )
                if dup_result.scalars().first() is not None:
                    logfire.warning(
                        f"Duplicate value for {parameter_code} in TestResult {tr.id}, skipping"
                    )
                else:
                    # 6. Construir RawLabValueInput
                    raw_input = RawLabValueInput(
                        parameter_code=parameter_code,
                        parameter_name_es=param_name_es,
                        raw_value=raw_value,
                        numeric_value=numeric_value,
                        unit=param_unit,
                        reference_range=get_reference_range(parameter_code, normalized_patient.species),
                        machine_flag=None,
                    )

                    # 7. Flag y guardar
                    await taller_svc.flag_and_store(
                        test_result_id=tr.id,
                        species=normalized_patient.species,
                        values=[raw_input],
                        session=session,
                    )
                    logger.info(f"Fujifilm lab value {parameter_code}={raw_value} stored in TestResult {tr.id}.")
                    logfire.info(f"Fujifilm lab value {parameter_code}={raw_value} stored in TestResult {tr.id}.")
            else:
                logger.info("Fujifilm: No parameter_code or raw_value provided, skipping lab value processing.")
                logfire.info("Fujifilm: No parameter_code or raw_value provided, skipping lab value processing.")

            logger.info("Fujifilm pipeline completado exitosamente.")
            logfire.info("Fujifilm pipeline completado exitosamente.")

    except Exception as e:
        logger.error(f"Error crítico en pipeline Fujifilm: {e}", exc_info=True)
        logfire.error(f"Error crítico en pipeline Fujifilm: {e}", exc_info=True)
        raise  # Let Dramatiq retry