from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import select
from sqlalchemy import delete
from app.domains.reception.schemas import PatientSource
from app.domains.patients.models import Patient
from app.services.appsheet import AppSheetPatient
from app.domains.exam_order.service import ExamOrderService
from app.domains.reception.helpers import _resolve_appsheet_test_type
from app.domains.reception.baul import _normalize_for_comparison
from app.services.provenance_recorder import ProvenanceRecorder
import logfire


class AppSheetSyncService:
    """Handles AppSheet synchronization: sync patients from AppSheet data
    and clear all active patients from the waiting room.

    Extracted from ReceptionService as part of the Strangler Fig
    refactoring (PR #6). Zero behavioral change — verbatim copy.
    """

    def __init__(self):
        self._exam_order_service = ExamOrderService()

    async def _try_link_raw_data(
        self,
        session: AsyncSession,
        session_code: str | None,
        patient_id: int,
    ) -> None:
        """Backfill RawDataLog.patient_id for rows captured before entity resolution.

        Wrapped in try/except — linking failures never propagate.
        """
        if not session_code:
            return
        try:
            await ProvenanceRecorder.link_to_patient(
                session=session,
                session_code=session_code,
                patient_id=patient_id,
            )
        except Exception:
            logfire.warning(
                f"Lazy linking failed for session_code={session_code}",
                _exc_info=True,
            )

    async def sync_from_appsheet(
        self, patients: list[AppSheetPatient], session: AsyncSession, reset: bool = False
    ) -> int:
        """Sincroniza pacientes desde AppSheet, creando o actualizando registros."""
        if reset:
            await self.clear_all_active_patients(session)

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
                await self._try_link_raw_data(
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
                await self._try_link_raw_data(
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
