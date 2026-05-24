from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import select
from app.domains.reception.schemas import RawPatientInput, BaulResult, PatientSource
from app.domains.patients.models import Patient

from app.shared.models.test_result import TestResult
from app.domains.reception.merge_service import TestResultMergeService
from app.services.appsheet import AppSheetPatient
from app.domains.exam_order.service import ExamOrderService
from sqlalchemy import delete
import logfire


from app.domains.reception.helpers import (
    _resolve_appsheet_test_type,
)
from app.domains.reception.query_service import WaitingRoomQueryService
from app.domains.reception.upload_handler import FileUploadHandler
from app.domains.reception.intake_service import PatientIntakeService


class ReceptionService:
    """Orchestrates the full reception flow:
    RawPatientInput → normalize → Baúl → BaulResult
    """

    def __init__(self):
        from app.domains.reception.archive_service import PatientArchiveService
        from app.domains.reception.delete_service import PatientDeleteService

        self._exam_order_service = ExamOrderService()
        self._archive = PatientArchiveService()
        self._delete = PatientDeleteService()
        self._query = WaitingRoomQueryService()
        self._upload = FileUploadHandler(receive_fn=self.receive)
        self._merge = TestResultMergeService()
        self._intake = PatientIntakeService()

    async def receive(
        self, raw_input: RawPatientInput, session: AsyncSession
    ) -> BaulResult:
        """Delegates to PatientIntakeService."""
        return await self._intake.receive(raw_input, session)

    async def sync_from_appsheet(
        self, patients: list[AppSheetPatient], session: AsyncSession, reset: bool = False
    ) -> int:
        """Sincroniza pacientes desde AppSheet, creando o actualizando registros."""
        if reset:
            await self.clear_all_active_patients(session)
            
        from app.domains.reception.baul import _normalize_for_comparison
        
        count = 0
        for ap in patients:
            norm_name = _normalize_for_comparison(ap.name)
            norm_owner = _normalize_for_comparison(ap.owner_name)

            # 1. Buscar por session_code PRIMERO
            stmt = select(Patient).where(Patient.session_code == ap.session_code)
            result = await session.execute(stmt)
            existing_patient = result.scalar_one_or_none()

            if existing_patient:
                patient_id = existing_patient.id
                # Actualizar paciente existente
                existing_patient.name = ap.name
                existing_patient.species = ap.species
                existing_patient.sex = ap.gender
                existing_patient.owner_name = ap.owner_name
                existing_patient.breed = ap.breed
                existing_patient.doctor_name = ap.vet_name or None
                appsheet_type, appsheet_code = _resolve_appsheet_test_type(ap.test_type)
                existing_patient.appsheet_test_type = appsheet_type
                existing_patient.appsheet_test_type_code = appsheet_code

                # Manejar edad
                try:
                    existing_patient.age_value = int(ap.age_number)
                except (ValueError, TypeError):
                    existing_patient.age_value = None

                existing_patient.age_unit = ap.age_unit.lower() if ap.age_unit else None
                existing_patient.age_display = f"{ap.age_number} {ap.age_unit}" if ap.age_number and ap.age_unit else None
                existing_patient.has_age = bool(ap.age_number and ap.age_unit)

                if PatientSource.APPSHEET.value not in existing_patient.sources_received:
                    existing_patient.sources_received.append(PatientSource.APPSHEET.value)
                    flag_modified(existing_patient, "sources_received")

                existing_patient.updated_at = datetime.now(timezone.utc)
                session.add(existing_patient)
                # Lazy linking for AppSheet sync update
                await self._intake._try_link_raw_data(
                    session, ap.session_code, patient_id
                )
            else:
                # Crear nuevo paciente limpio y fresco
                appsheet_type, appsheet_code = _resolve_appsheet_test_type(ap.test_type)
                new_patient = Patient(
                    name=ap.name,
                    species=ap.species,
                    sex=ap.gender,
                    owner_name=ap.owner_name,
                    breed=ap.breed,
                    doctor_name=ap.vet_name or None,
                    appsheet_test_type=appsheet_type,
                    appsheet_test_type_code=appsheet_code,
                    session_code=ap.session_code,
                    source=PatientSource.APPSHEET.value,
                    sources_received=[PatientSource.APPSHEET.value],
                    normalized_name=norm_name,
                    normalized_owner=norm_owner,
                    age_value=int(ap.age_number) if ap.age_number and ap.age_number.isdigit() else None,
                    age_unit=ap.age_unit.lower() if ap.age_unit else None,
                    age_display=f"{ap.age_number} {ap.age_unit}" if ap.age_number and ap.age_unit else None,
                    has_age=bool(ap.age_number and ap.age_unit)
                )
                session.add(new_patient)
                await session.flush()  # Get patient ID before creating ExamOrder
                patient_id = new_patient.id
                # Lazy linking for AppSheet sync creation
                await self._intake._try_link_raw_data(
                    session, ap.session_code, patient_id
                )

            # ── Create/update ExamOrder from AppSheet data ─────────────
            order_data = {
                "Codigo_Corto": ap.session_code,
                "Examen_Especifico": ap.test_type,
                "Paciente_ID": str(patient_id),
            }
            try:
                await self._exam_order_service.create_from_appsheet(order_data, session)
            except Exception as e:
                logfire.warning(
                    f"Error creating ExamOrder for patient {patient_id} "
                    f"(session={ap.session_code}): {e}"
                )

            count += 1

        await session.commit()
        return count

    async def clear_all_active_patients(self, session: AsyncSession) -> int:
        """Deletes all patients from the waiting room (active patients)."""
        logfire.info("Limpiando todos los pacientes activos de la recepción.")
        stmt = delete(Patient).where(Patient.waiting_room_status == "active")
        result = await session.execute(stmt)
        await session.commit()
        # Note: rowcount might not be reliable on all async drivers, 
        # but it works for our Postgres/SQLite needs here.
        count = result.rowcount if hasattr(result, "rowcount") else 0
        logfire.info(f"Limpieza completada: {count} pacientes eliminados.")
        return count

    async def get_waiting_room_patients(
        self, session: AsyncSession
    ) -> list[dict]:
        """Delegates to WaitingRoomQueryService."""
        return await self._query.get_waiting_room_patients(session)

    async def delete_patient_from_waiting_room(
        self, patient_id: int, session: AsyncSession
    ) -> bool:
        """Delegates to PatientDeleteService."""
        return await self._delete.delete_patient_from_waiting_room(patient_id, session)

    async def inject_patient_to_taller(
        self, patient_id: int, session: AsyncSession
    ) -> TestResult | None:
        """Delegates to TestResultMergeService."""
        return await self._merge.inject_patient_to_taller(patient_id, session)

    async def handle_uploaded_file(self, file_content: bytes, file_type: str, session: AsyncSession) -> str:
        """Delegates to FileUploadHandler."""
        return await self._upload.handle_uploaded_file(file_content, file_type, session)

    # ── Archiving (soft-hide via status flag) ──────────────────────────

    async def archive_all_active(self, session: AsyncSession) -> int:
        """Delegates to PatientArchiveService."""
        return await self._archive.archive_all_active(session)

    async def restore_all_archived(self, session: AsyncSession) -> int:
        """Delegates to PatientArchiveService."""
        return await self._archive.restore_all_archived(session)

    async def restore_single_archived(self, patient_id: int, session: AsyncSession) -> bool:
        """Delegates to PatientArchiveService."""
        return await self._archive.restore_single_archived(patient_id, session)

    async def get_archived_patients(self, session: AsyncSession) -> list[dict]:
        """Delegates to PatientArchiveService."""
        return await self._archive.get_archived_patients(session)

    async def get_single_patient_for_card(
        self, patient_id: int, session: AsyncSession
    ) -> dict | None:
        """Delegates to WaitingRoomQueryService."""
        return await self._query.get_single_patient_for_card(patient_id, session)