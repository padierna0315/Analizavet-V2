from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import select
from app.domains.reception.schemas import RawPatientInput, BaulResult, PatientSource, NormalizedPatient
from app.domains.reception.normalizer import parse_patient_string
from app.domains.reception.baul import BaulService
from app.domains.patients.models import Patient

from app.shared.models.test_result import TestResult
from app.domains.reception.merge_service import TestResultMergeService
from app.services.appsheet import AppSheetPatient
from app.domains.exam_order.service import ExamOrderService
from app.services.provenance_recorder import ProvenanceRecorder
from app.shared.models.data_quarantine import DataQuarantine
from sqlalchemy import delete
import logfire


from app.domains.reception.helpers import (
    _sanitize_patient_age,
    _resolve_appsheet_test_type,
)
from app.domains.reception.query_service import WaitingRoomQueryService
from app.domains.reception.upload_handler import FileUploadHandler


class ReceptionService:
    """Orchestrates the full reception flow:
    RawPatientInput → normalize → Baúl → BaulResult
    """

    def __init__(self):
        from app.domains.reception.archive_service import PatientArchiveService
        from app.domains.reception.delete_service import PatientDeleteService

        self._baul = BaulService()
        self._exam_order_service = ExamOrderService()
        self._archive = PatientArchiveService()
        self._delete = PatientDeleteService()
        self._query = WaitingRoomQueryService()
        self._upload = FileUploadHandler(receive_fn=self.receive)
        self._merge = TestResultMergeService()

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

    async def receive(
        self, raw_input: RawPatientInput, session: AsyncSession
    ) -> BaulResult:
        logfire.info(
            f"Recibiendo paciente: '{raw_input.raw_string}' "
            f"(code={raw_input.session_code}) "
            f"[fuente={raw_input.source.value}]"
        )

        # 1. Buscar por session_code PRIMERO (only if session_code is present)
        lookup_code = raw_input.session_code

        # Only attempt session_code lookup if code is present
        if lookup_code:
            stmt = select(Patient).where(Patient.session_code == lookup_code)
            result = await session.execute(stmt)
            existing_patient = result.scalar_one_or_none()
        else:
            existing_patient = None

        if existing_patient:
            # ── Temporal isolation check (R7) ──────────────────────────────
            # Prevent data from a different session era from attaching to an
            # existing patient that shares the same session_code.  5-second
            # tolerance covers clock skew and batch upload timing.
            tolerance = timedelta(seconds=5)
            # Normalize to naive for comparison — SQLite may strip timezone info.
            received_naive = raw_input.received_at.replace(tzinfo=None) \
                if raw_input.received_at.tzinfo is not None \
                else raw_input.received_at
            created_naive = existing_patient.created_at.replace(tzinfo=None) \
                if existing_patient.created_at.tzinfo is not None \
                else existing_patient.created_at
            if received_naive < created_naive - tolerance:
                logfire.error(
                    "Temporal mismatch: data received {received_at} "
                    "but patient created {created_at} "
                    "(session_code={code})".format(
                        received_at=raw_input.received_at,
                        created_at=existing_patient.created_at,
                        code=lookup_code,
                    )
                )
                try:
                    q = DataQuarantine(
                        source=raw_input.source.value,
                        raw_data=raw_input.raw_string,
                        received_at=raw_input.received_at,
                        rejection_reason="temporal_mismatch",
                    )
                    session.add(q)
                    await session.commit()
                except Exception:
                    logfire.warning(
                        "Failed to insert quarantine record for temporal mismatch",
                        _exc_info=True,
                    )
                # Do NOT attach to this patient — force creation of a new one.
                existing_patient = None
            # ── end temporal check ─────────────────────────────────────────

        if existing_patient:
            logfire.info(
                f"Paciente encontrado por código corto: {existing_patient.name} "
                f"({existing_patient.session_code}) [id={existing_patient.id}]"
            )
            
            # Append new source if not present
            new_source_value = raw_input.source.value
            if new_source_value not in existing_patient.sources_received:
                existing_patient.sources_received.append(new_source_value)
                flag_modified(existing_patient, "sources_received")
            
            existing_patient.updated_at = datetime.now(timezone.utc)
            session.add(existing_patient)
            await session.commit()
            await session.refresh(existing_patient)

            # Lazy linking: backfill RawDataLog.patient_id
            await self._try_link_raw_data(
                session, raw_input.session_code, existing_patient.id
            )

            # Sanitize age fields from DB (defensive — Patient model has no cross-field validator)
            sanitized_has_age, sanitized_age_value, sanitized_age_unit, sanitized_age_display = \
                _sanitize_patient_age(
                    existing_patient.has_age,
                    existing_patient.age_value,
                    existing_patient.age_unit,
                    existing_patient.age_display,
                )

            # Write-back: heal inconsistent DB data
            if (existing_patient.has_age != sanitized_has_age or 
                existing_patient.age_value != sanitized_age_value):
                existing_patient.has_age = sanitized_has_age
                existing_patient.age_value = sanitized_age_value
                existing_patient.age_unit = sanitized_age_unit
                existing_patient.age_display = sanitized_age_display
                session.add(existing_patient)
                await session.commit()
                await session.refresh(existing_patient)

            # Convert Patient to NormalizedPatient for the result
            normalized = NormalizedPatient(
                name=existing_patient.name,
                species=existing_patient.species,
                sex=existing_patient.sex,
                has_age=sanitized_has_age,
                age_value=sanitized_age_value,
                age_unit=sanitized_age_unit,
                age_display=sanitized_age_display,
                owner_name=existing_patient.owner_name,
                source=raw_input.source
            )
            
            return BaulResult(
                patient_id=existing_patient.id,
                created=False,
                patient=normalized,
            )

        # 2. Si no es un código corto, proceder con el flujo normal de normalización
        # Pasar species_override/sex_override si el parser HL7 los extrajo (PID[10]/PID[8])
        normalized = parse_patient_string(
            raw_input.raw_string,
            raw_input.source,
            species_override=raw_input.species_override,
            sex_override=raw_input.sex_override,
        )
        
        # Import the normalization function for deduplication
        from app.domains.reception.baul import _normalize_for_comparison
        
        norm_name = _normalize_for_comparison(normalized.name)
        norm_owner = _normalize_for_comparison(normalized.owner_name)
        
        # Check if patient already exists using deduplication key
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
            
            # Sanitize age from normalized data (defensive — normalized is model-validated, but be safe)
            sanitized_has_age, sanitized_age_value, sanitized_age_unit, sanitized_age_display = \
                _sanitize_patient_age(
                    normalized.has_age,
                    normalized.age_value,
                    normalized.age_unit,
                    normalized.age_display,
                )

            # Update demographic fields from new data
            # Only from non-machine sources (manual forms, AppSheet)
            # Machine sources (Ozelle, Fujifilm) only provide lab results — don't overwrite
            if raw_input.source not in (PatientSource.LIS_OZELLE, PatientSource.LIS_FILE, PatientSource.LIS_FUJIFILM):
                existing_patient.name = normalized.name
                existing_patient.species = normalized.species
                existing_patient.sex = normalized.sex
                existing_patient.owner_name = normalized.owner_name
                existing_patient.has_age = sanitized_has_age
                existing_patient.age_value = sanitized_age_value
                existing_patient.age_unit = sanitized_age_unit
                existing_patient.age_display = sanitized_age_display
            
            # Update timestamp
            existing_patient.updated_at = datetime.now(timezone.utc)
            
            session.add(existing_patient)
            await session.commit()
            await session.refresh(existing_patient)
            
            # Lazy linking: backfill RawDataLog.patient_id for merge match
            await self._try_link_raw_data(
                session, raw_input.session_code, existing_patient.id
            )

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
        result = await self._baul.register(normalized, session, session_code=raw_input.session_code)
        
        # Manually set the initial source for the new patient
        newly_created_patient = await session.get(Patient, result.patient_id)
        if newly_created_patient:
            newly_created_patient.sources_received.append(raw_input.source.value)
            flag_modified(newly_created_patient, "sources_received")
            session.add(newly_created_patient)
            await session.commit()
            await session.refresh(newly_created_patient)

        # Lazy linking: backfill RawDataLog.patient_id for new patient
        await self._try_link_raw_data(
            session, raw_input.session_code, result.patient_id
        )

        return result

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