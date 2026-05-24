"""
FileUploadHandler — extracted from ReceptionService.handle_uploaded_file (PR #3).

Routes uploaded file content to the correct parser/handler based on file_type.
Returns the upload_id for status tracking.
"""
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Callable, Awaitable

import json
import logfire
import uuid

from app.tasks.hl7_processor import set_upload_status, init_upload_counter
from app.domains.reception.schemas import RawPatientInput, PatientSource, BaulResult
from app.tasks.hl7_processor import split_hl7_batch, _async_process_pipeline
from app.satellites.ozelle.hl7_parser import parse_hl7_message, HeartbeatMessageException, HL7ParsingError


class FileUploadHandler:
    """
    Handles routing of uploaded files to the appropriate parser.

    Accepts a receive callback to delegate JSON baptism processing
    back to ReceptionService.receive (or equivalent intake method).
    """

    def __init__(
        self,
        receive_fn: Callable[..., Awaitable[BaulResult]] | None = None,
    ):
        self._receive = receive_fn

    async def handle_uploaded_file(
        self, file_content: bytes, file_type: str, session: AsyncSession
    ) -> str:
        """
        Routes uploaded file content to the correct parser/handler based on file_type.
        Returns the upload_id for status tracking.
        """
        logfire.info(f"Handling uploaded file of type {file_type}")

        content_str = file_content.decode("utf-8", errors="ignore")
        upload_id = str(uuid.uuid4())  # Generate a unique ID for this upload
        set_upload_status(upload_id, "processing")  # Set initial status to Redis

        match file_type:
            case "ozelle":
                # Procesar directamente — los archivos son pequeños y el parsing es rápido
                messages = split_hl7_batch(content_str)
                count = 0
                for msg in messages:
                    try:
                        parsed = parse_hl7_message(msg, "LIS_OZELLE")
                        await _async_process_pipeline(parsed, "LIS_OZELLE")
                        count += 1
                    except HeartbeatMessageException:
                        continue
                    except (HL7ParsingError, Exception) as e:
                        logfire.error(f"Error procesando mensaje del batch: {e}")
                        continue

                set_upload_status(upload_id, f"complete:{count}")
                logfire.info(f"Procesados {count} pacientes del archivo Ozelle.")

            case "fujifilm":
                from app.satellites.fujifilm.parser import parse_fujifilm_message, FujifilmReading
                from app.tasks.fujifilm_processor import process_fujifilm_message

                records = parse_fujifilm_message(content_str)
                count = 0
                batch_received_at = datetime.now(timezone.utc).isoformat()  # mismo timestamp para todo el batch
                for record in records:
                    # 'record' is a FujifilmReading object
                    process_fujifilm_message.send(
                        {
                            "internal_id": record.internal_id,
                            "patient_name": record.patient_name,
                            "parameter_code": record.parameter_code,
                            "raw_value": record.raw_value,
                            "source": PatientSource.LIS_FUJIFILM.value,
                            "received_at": batch_received_at,
                            "upload_id": upload_id,
                        }
                    )
                    count += 1
                # Use counter-based tracking so "complete" reflects actual processing
                init_upload_counter(upload_id, count)
                logfire.info(f"Enqueued {count} Fujifilm records for Dramatiq processing.")

            case "json":
                try:
                    data = json.loads(content_str)
                    if "raw_string" not in data:
                        raise ValueError(
                            "El archivo JSON para bautizar debe contener la clave 'raw_string'."
                        )

                    raw_input = RawPatientInput(
                        raw_string=data["raw_string"],
                        source="MANUAL",
                        received_at=datetime.now(timezone.utc),
                    )
                    await self._receive(raw_input, session)
                    logfire.info("Processed JSON baptism file.")

                except json.JSONDecodeError:
                    raise ValueError("El archivo JSON está malformado.")
                except Exception as e:
                    logfire.error(f"Error processing JSON file: {e}")
                    raise ValueError(f"Error inesperado al procesar el archivo JSON: {e}")

            case _:
                # If file_type is unknown, set error status and raise exception
                set_upload_status(upload_id, f"error:Tipo de archivo no soportado: '{file_type}'")
                raise ValueError(f"Tipo de archivo no soportado: '{file_type}'")

        return upload_id  # Return the upload_id for the frontend to poll
