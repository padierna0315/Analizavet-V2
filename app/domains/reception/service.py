from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import select
from app.domains.reception.schemas import RawPatientInput, BaulResult
from app.domains.reception.normalizer import parse_patient_string
from app.domains.reception.baul import BaulService
from app.domains.patients.models import Patient
from app.tasks.hl7_processor import process_hl7_message, process_uploaded_batch, set_upload_status
from app.shared.models.test_result import TestResult
from app.shared.models.lab_value import LabValue # Added this
from sqlalchemy.orm import selectinload # Added this # Added this line
import json
import logfire
import uuid



class ReceptionService:
    """Orchestrates the full reception flow:
    RawPatientInput → normalize → Baúl → BaulResult
    """

    def __init__(self):
        self._baul = BaulService()

    async def receive(
        self, raw_input: RawPatientInput, session: AsyncSession
    ) -> BaulResult:
        logfire.info(
            f"Recibiendo paciente: '{raw_input.raw_string}' "
            f"[fuente={raw_input.source.value}]"
        )
        normalized = parse_patient_string(raw_input.raw_string, raw_input.source)
        
        # Import the normalization function for deduplication
        from app.domains.reception.baul import _normalize_for_comparison
        
        # Check if patient already exists using deduplication key
        norm_name = _normalize_for_comparison(normalized.name)
        norm_owner = _normalize_for_comparison(normalized.owner_name)
        
        existing_patient = await self._baul._find_existing(
            session, norm_name, norm_owner, normalized.species
        )
        
        if existing_patient:
            # Patient exists - implement merge logic
            logfire.info(
                f"Paciente existente encontrado: {normalized.name} ({normalized.species}) "
                f"- Tutor: {normalized.owner_name} [id={existing_patient.id}]"
            )
            
            # Append new source if not present
            new_source_value = raw_input.source.value
            if new_source_value not in existing_patient.sources_received:
                existing_patient.sources_received.append(new_source_value)
                # Mark the mutable list as modified for SQLAlchemy to detect the change
                flag_modified(existing_patient, "sources_received")
            
            # Update demographic fields from new data
            existing_patient.name = normalized.name
            existing_patient.species = normalized.species
            existing_patient.sex = normalized.sex
            existing_patient.owner_name = normalized.owner_name
            existing_patient.has_age = normalized.has_age
            existing_patient.age_value = normalized.age_value
            existing_patient.age_unit = normalized.age_unit
            existing_patient.age_display = normalized.age_display
            
            # Update timestamp
            existing_patient.updated_at = datetime.now(timezone.utc)
            
            session.add(existing_patient)
            await session.commit()
            await session.refresh(existing_patient)
            
            logfire.info(
                f"Paciente actualizado: {normalized.name} ({normalized.species}) "
                f"- Tutor: {normalized.owner_name} [id={existing_patient.id}]"
            )
            
            return BaulResult(
                patient_id=existing_patient.id,
                created=False,
                patient=normalized,
            )
        
        # Create new patient (existing flow)
        result = await self._baul.register(normalized, session)
        
        # Manually set the initial source for the new patient
        newly_created_patient = await session.get(Patient, result.patient_id)
        if newly_created_patient:
            newly_created_patient.sources_received.append(raw_input.source.value)
            flag_modified(newly_created_patient, "sources_received")
            session.add(newly_created_patient)
            await session.commit()
            await session.refresh(newly_created_patient)

        return result

    async def get_waiting_room_patients(
        self, session: AsyncSession
    ) -> list[dict]:
        """Get all patients currently in the waiting room (sala de espera).
        
        Returns patients with waiting_room_status = 'active' formatted for display.
        """
        from app.shared.models.test_result import TestResult
        query = select(Patient).where(Patient.waiting_room_status == "active")
        query = query.order_by(Patient.updated_at.desc())
        
        result = await session.execute(query)
        patients = result.scalars().all()
        
        # Format patient data for the waiting room UI
        patients_data = []
        for patient in patients:
            sources_received = list(patient.sources_received or [])
            
            # Get the most recent TestResult id for this patient
            tr_query = (
                select(TestResult.id)
                .where(TestResult.patient_id == patient.id)
                .order_by(TestResult.id.desc())
                .limit(1)
            )
            tr_result = await session.execute(tr_query)
            latest_result_id = tr_result.scalar_one_or_none()
            
            patient_data = {
                "id": patient.id,
                "result_id": latest_result_id,
                "name": patient.name,
                "species": patient.species,
                "sex": patient.sex,
                "owner_name": patient.owner_name,
                "age_display": patient.age_display,
                "session_code": patient.session_code,
                "waiting_room_status": patient.waiting_room_status,
                "sources_received": sources_received,
                "created_at": patient.created_at.isoformat() if patient.created_at else None,
                "updated_at": patient.updated_at.isoformat() if patient.updated_at else None,
                "source": patient.source,
                "normalized_name": patient.normalized_name,
                "normalized_owner": patient.normalized_owner
            }
            patients_data.append(patient_data)
        
        return patients_data

    async def delete_patient_from_waiting_room(
        self, patient_id: int, session: AsyncSession
    ) -> bool:
        """
        Deletes a patient record from the database.

        Returns True if the patient was found and deleted, False otherwise.
        """
        logfire.info(f"Attempting to delete patient with id={patient_id}")

        # Cargar toda la cadena en memoria para que el cascade ORM funcione:
        # Patient → TestResult → LabValue / PatientImage
        from sqlalchemy import select as sa_select
        from sqlalchemy.orm import selectinload
        from app.shared.models.test_result import TestResult
        from app.shared.models.lab_value import LabValue
        from app.shared.models.patient_image import PatientImage
        stmt = (
            sa_select(Patient)
            .where(Patient.id == patient_id)
            .options(
                selectinload(Patient.test_results).options(
                    selectinload(TestResult.lab_values),
                    selectinload(TestResult.images),
                )
            )
        )
        result = await session.execute(stmt)
        patient = result.scalar_one_or_none()

        if patient:
            await session.delete(patient)
            await session.commit()
            logfire.info(f"Successfully deleted patient with id={patient_id}")
            return True
        else:
            logfire.warning(f"Patient with id={patient_id} not found for deletion.")
            return False

    async def inject_patient_to_taller(
        self, patient_id: int, session: AsyncSession
    ) -> TestResult | None:
        """
        Loads the latest TestResult for a patient into Taller.
        No filtering by status — if the patient is in the waiting room, their data is injectable.
        """
        logfire.info(f"Attempting to inject patient {patient_id} test results to Taller.")

        statement = (
            select(TestResult)
            .where(TestResult.patient_id == patient_id)
            .order_by(TestResult.id.desc())
            .limit(1)
        )
        result = await session.execute(statement)
        test_result = result.scalars().first()

        if not test_result:
            logfire.warning(f"No TestResult found for patient {patient_id}.")
            return None

        logfire.info(f"Found TestResult {test_result.id} (status={test_result.status}) for patient {patient_id}.")
        return test_result

    async def handle_uploaded_file(self, file_content: bytes, file_type: str, session: AsyncSession) -> str:
        """
        Routes uploaded file content to the correct parser/handler based on file_type.
        Returns the upload_id for status tracking.
        """
        logfire.info(f"Handling uploaded file of type {file_type}")
        
        content_str = file_content.decode('utf-8', errors='ignore')
        upload_id = str(uuid.uuid4()) # Generate a unique ID for this upload
        set_upload_status(upload_id, "processing") # Set initial status to Redis

        match file_type:
            case "ozelle":
                # Procesar directamente — los archivos son pequeños y el parsing es rápido
                from app.tasks.hl7_processor import split_hl7_batch
                from app.satellites.ozelle.hl7_parser import parse_hl7_message, HeartbeatMessageException, HL7ParsingError
                from app.tasks.hl7_processor import _async_process_pipeline
                
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
                for record in records:
                    # 'record' is a FujifilmReading object
                    process_fujifilm_message.send({
                        "internal_id": record.internal_id,
                        "patient_name": record.patient_name,
                        "parameter_code": record.parameter_code,
                        "raw_value": record.raw_value,
                        "source": "FUJIFILM",
                        "received_at": datetime.now(timezone.utc).isoformat()
                    })
                    count += 1
                set_upload_status(upload_id, f"complete:{count}")
                logfire.info(f"Enqueued {count} Fujifilm records for Dramatiq processing.")
            
            case "json":
                try:
                    data = json.loads(content_str)
                    if "raw_string" not in data:
                        raise ValueError("El archivo JSON para bautizar debe contener la clave 'raw_string'.")
                    
                    raw_input = RawPatientInput(
                        raw_string=data["raw_string"],
                        source='MANUAL',
                        received_at=datetime.now(timezone.utc)
                    )
                    await self.receive(raw_input, session)
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
        
        return upload_id # Return the upload_id for the frontend to poll

    async def get_single_patient_for_card(
        self, patient_id: int, session: AsyncSession
    ) -> dict | None:
        """Gets a single patient's data formatted for the waiting room card."""
        patient = await session.get(Patient, patient_id)
        if not patient:
            return None
            
        # This logic is duplicated from get_waiting_room_patients.
        # Consider refactoring into a helper function in the future.
        # sources_received is now a Python list (TypeDecorator handles deserialization)
        sources_received = list(patient.sources_received or [])
        
        patient_data = {
            "id": patient.id,
            "name": patient.name,
            "species": patient.species,
            "sex": patient.sex,
            "owner_name": patient.owner_name,
            "age_display": patient.age_display,
            "session_code": patient.session_code,
            "waiting_room_status": patient.waiting_room_status,
            "sources_received": sources_received,
            "created_at": patient.created_at.isoformat() if patient.created_at else None,
            "updated_at": patient.updated_at.isoformat() if patient.updated_at else None,
            "source": patient.source,
            "normalized_name": patient.normalized_name,
            "normalized_owner": patient.normalized_owner
        }
        return patient_data