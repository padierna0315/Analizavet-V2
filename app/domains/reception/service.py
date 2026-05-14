from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import select
from app.domains.reception.schemas import RawPatientInput, BaulResult, PatientSource, NormalizedPatient
from app.domains.reception.normalizer import parse_patient_string
from app.domains.reception.baul import BaulService
from app.domains.patients.models import Patient
from app.tasks.hl7_processor import process_hl7_message, process_uploaded_batch, set_upload_status
from app.shared.models.test_result import TestResult
from app.shared.models.lab_value import LabValue # Added this
from app.services.appsheet import AppSheetPatient
from app.domains.exam_order.service import ExamOrderService
from sqlalchemy.orm import selectinload
from sqlalchemy import delete
import json
import logfire
import uuid


def _sanitize_patient_age(has_age: bool, age_value: int | None, age_unit: str | None, age_display: str | None) -> tuple[bool, int | None, str | None, str | None]:
    """Ensure age field consistency. If has_age is False or age_value is None, all fields must be None."""
    if has_age and age_value is not None:
        return has_age, age_value, age_unit, age_display
    return False, None, None, None


# ── AppSheet test_type mapping ─────────────────────────────────────────────────
# Mapeo de Examen_Especifico (AppSheet) → (test_type_display, test_type_code)
# Ordenado de más específico a menos específico para matching exacto.
_APPSHEET_TEST_TYPE_MAP: dict[str, tuple[str, str]] = {
    "Coprologico seriado 3": ("Coprológico Seriado 3", "COPROSC"),
    "Coprologico seriado 2": ("Coprológico Seriado 2", "COPROSC"),
    "Coprologico seriado 1": ("Coprológico Seriado 1", "COPROSC"),
    "Coprologico": ("Coprológico", "COPROSC"),
    "Citoquimico": ("Citoquímico", "CITO"),
    "Perfil Hepatico": ("Perfil Hepático", "CHEM"),
    "Perfil Renal": ("Perfil Renal", "CHEM"),
    "Perfil Basico": ("Perfil Básico", "CHEM"),
}

# Valor por defecto cuando AppSheet no especifica el tipo de examen
_DEFAULT_APPSHEET_TEST_TYPE = ("Química Sanguínea", "CHEM")

# Mapeo de categoría de catálogo → test_type_code (código corto)
_CATEGORY_TO_CODE: dict[str, str] = {
    "Química Sanguínea": "CHEM",
    "Hematología": "CBC",
    "Coprología": "COPROSC",
    "Orina": "URINE",
    "Dermatología": "DERM",
}


def _resolve_appsheet_test_type(examen_especifico: str | None) -> tuple[str, str]:
    """Resuelve Examen_Especifico de AppSheet a (test_type, test_type_code).

    Si el valor no está en el mapa (None o desconocido), retorna el default.
    """
    if not examen_especifico:
        return _DEFAULT_APPSHEET_TEST_TYPE
    return _APPSHEET_TEST_TYPE_MAP.get(examen_especifico.strip(), _DEFAULT_APPSHEET_TEST_TYPE)


def _resolve_test_type_from_exam_types(exam_types: list[str]) -> tuple[str, str] | None:
    """Resolve ExamOrder ``exam_types`` codes to ``(test_type, test_type_code)``.

    Uses the first exam type code to look up the catalog entry.
    Returns ``None`` when the list is empty, so the caller can fall back to
    ``Patient.appsheet_test_type`` for backward compatibility.
    """
    if not exam_types:
        return None

    from app.shared.catalogs.appsheet_exam_catalog import EXAM_CATALOG

    first_code = exam_types[0]
    entry = EXAM_CATALOG.get(first_code)
    if entry:
        category_code = _CATEGORY_TO_CODE.get(entry["category"], "CHEM")
        return (entry["display_name"], category_code)

    return None


class ReceptionService:
    """Orchestrates the full reception flow:
    RawPatientInput → normalize → Baúl → BaulResult
    """

    def __init__(self):
        self._baul = BaulService()
        self._exam_order_service = ExamOrderService()

    async def receive(
        self, raw_input: RawPatientInput, session: AsyncSession
    ) -> BaulResult:
        logfire.info(
            f"Recibiendo paciente: '{raw_input.raw_string}' "
            f"(code={raw_input.session_code}) "
            f"[fuente={raw_input.source.value}]"
        )

        # 1. Buscar por session_code PRIMERO
        lookup_code = raw_input.session_code or raw_input.raw_string
        stmt = select(Patient).where(Patient.session_code == lookup_code)
        result = await session.execute(stmt)
        existing_patient = result.scalar_one_or_none()

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
        
        # ── FUJIFILM: buscar por nombre únicamente ──────────────────────
        # La máquina solo envía el nombre, sin especie/edad/tutor.
        # Si ya existe un paciente con ese nombre, lo vinculamos.
        if raw_input.source == PatientSource.LIS_FUJIFILM:
            stmt = select(Patient).where(Patient.normalized_name == norm_name)
            result = await session.execute(stmt)
            fuji_match = result.scalars().first()
            
            if fuji_match:
                logfire.info(
                    f"Fujifilm: paciente encontrado por nombre: {fuji_match.name} "
                    f"[id={fuji_match.id}]"
                )
                new_source = PatientSource.LIS_FUJIFILM.value
                if new_source not in fuji_match.sources_received:
                    fuji_match.sources_received.append(new_source)
                    flag_modified(fuji_match, "sources_received")
                # Backfill session_code si vino en el mensaje y el paciente no tiene
                if raw_input.session_code and not fuji_match.session_code:
                    fuji_match.session_code = raw_input.session_code
                fuji_match.updated_at = datetime.now(timezone.utc)
                session.add(fuji_match)
                await session.commit()
                await session.refresh(fuji_match)
                
                # Sanitize age fields from DB (defensive — Patient model has no cross-field validator)
                sanitized_has_age, sanitized_age_value, sanitized_age_unit, sanitized_age_display = \
                    _sanitize_patient_age(
                        fuji_match.has_age,
                        fuji_match.age_value,
                        fuji_match.age_unit,
                        fuji_match.age_display,
                    )

                # Write-back: heal inconsistent DB data
                if (fuji_match.has_age != sanitized_has_age or 
                    fuji_match.age_value != sanitized_age_value):
                    fuji_match.has_age = sanitized_has_age
                    fuji_match.age_value = sanitized_age_value
                    fuji_match.age_unit = sanitized_age_unit
                    fuji_match.age_display = sanitized_age_display
                    session.add(fuji_match)
                    await session.commit()
                    await session.refresh(fuji_match)

                normalized = NormalizedPatient(
                    name=fuji_match.name,
                    species=fuji_match.species,
                    sex=fuji_match.sex,
                    has_age=sanitized_has_age,
                    age_value=sanitized_age_value,
                    age_unit=sanitized_age_unit,
                    age_display=sanitized_age_display,
                    owner_name=fuji_match.owner_name,
                    source=raw_input.source,
                )
                return BaulResult(
                    patient_id=fuji_match.id,
                    created=False,
                    patient=normalized,
                )
            
            # No existe — seguir flujo normal (creará paciente con "Desconocida")
        
        # ── OZELLE / FILE: buscar por nombre únicamente ────────────────────
        if raw_input.source in (PatientSource.LIS_OZELLE, PatientSource.LIS_FILE):
            stmt = select(Patient).where(Patient.normalized_name == norm_name)
            result = await session.execute(stmt)
            ozelle_match = result.scalars().first()
            
            if ozelle_match:
                logfire.info(
                    f"Ozelle/File: paciente encontrado por nombre: {ozelle_match.name} "
                    f"[id={ozelle_match.id}]"
                )
                # Add source
                new_source = raw_input.source.value
                if new_source not in ozelle_match.sources_received:
                    ozelle_match.sources_received.append(new_source)
                    flag_modified(ozelle_match, "sources_received")
                # Backfill session_code si vino en el mensaje y el paciente no tiene
                if raw_input.session_code and not ozelle_match.session_code:
                    ozelle_match.session_code = raw_input.session_code
                ozelle_match.updated_at = datetime.now(timezone.utc)
                session.add(ozelle_match)
                await session.commit()
                await session.refresh(ozelle_match)
                
                # Sanitize age fields from DB
                sanitized_has_age, sanitized_age_value, sanitized_age_unit, sanitized_age_display = \
                    _sanitize_patient_age(
                        ozelle_match.has_age,
                        ozelle_match.age_value,
                        ozelle_match.age_unit,
                        ozelle_match.age_display,
                    )
                
                # Write-back: heal inconsistent DB data
                if (ozelle_match.has_age != sanitized_has_age or 
                    ozelle_match.age_value != sanitized_age_value):
                    ozelle_match.has_age = sanitized_has_age
                    ozelle_match.age_value = sanitized_age_value
                    ozelle_match.age_unit = sanitized_age_unit
                    ozelle_match.age_display = sanitized_age_display
                    session.add(ozelle_match)
                    await session.commit()
                    await session.refresh(ozelle_match)
                
                normalized = NormalizedPatient(
                    name=ozelle_match.name,
                    species=ozelle_match.species,
                    sex=ozelle_match.sex,
                    has_age=sanitized_has_age,
                    age_value=sanitized_age_value,
                    age_unit=sanitized_age_unit,
                    age_display=sanitized_age_display,
                    owner_name=ozelle_match.owner_name,
                    source=raw_input.source,
                )
                return BaulResult(
                    patient_id=ozelle_match.id,
                    created=False,
                    patient=normalized,
                )
        
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

            # ── Look up active ExamOrders ─────────────────────────────
            exam_orders_list: list[dict] = []
            orders = await self._exam_order_service.get_by_patient(patient.id, session)
            for order in orders:
                exam_orders_list.append({
                    "id": order.id,
                    "session_code": order.session_code,
                    "exam_types": order.exam_types,
                    "status": order.status,
                })

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
                "exam_orders": exam_orders_list,
                "appsheet_test_type": patient.appsheet_test_type,
                "appsheet_test_type_code": patient.appsheet_test_type_code,
                "created_at": patient.created_at.isoformat() if patient.created_at else None,
                "updated_at": patient.updated_at.isoformat() if patient.updated_at else None,
                "source": patient.source,
                "normalized_name": patient.normalized_name,
                "normalized_owner": patient.normalized_owner,
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
        Loads ALL TestResults for a patient, merges them into a single TestResult,
        and returns the unified result for the Taller workspace.

        Handles:
        - Multiple sources (Ozelle + Fujifilm) → merged into one TR
        - Multiple parameters from same source (CRE + ALT) → merged into one TR
        - Duplicate parameters → skipped (first wins)
        - Race conditions → idempotent (merge always produces same result)
        """
        logfire.info(f"Attempting to inject patient {patient_id} test results to Taller.")

        # Load ALL TestResults for this patient (newest first)
        statement = (
            select(TestResult)
            .where(TestResult.patient_id == patient_id)
            .order_by(TestResult.id.desc())
        )
        result = await session.execute(statement)
        test_results = result.scalars().all()

        if not test_results:
            logfire.warning(f"No TestResult found for patient {patient_id}.")
            return None

        # Load Patient para datos de AppSheet (doctor_name)
        patient_result = await session.execute(select(Patient).where(Patient.id == patient_id))
        patient = patient_result.scalar_one_or_none()
        doctor_name = patient.doctor_name if patient else None

        # Resolve test_type from active ExamOrder first, fall back to Patient.appsheet_test_type
        exam_orders = await self._exam_order_service.get_by_patient(patient_id, session)
        active_orders = [o for o in exam_orders if o.status in ("pending", "partial")]
        exam_type_result = None
        if active_orders:
            exam_type_result = _resolve_test_type_from_exam_types(active_orders[0].exam_types)

        if exam_type_result:
            appsheet_test_type, appsheet_test_type_code = exam_type_result
        else:
            appsheet_test_type = patient.appsheet_test_type if patient else None
            appsheet_test_type_code = patient.appsheet_test_type_code if patient else None

        if len(test_results) == 1:
            # Single TR — nothing to merge, return as-is with doctor_name + exam type
            tr = test_results[0]
            if doctor_name and not tr.doctor_name:
                tr.doctor_name = doctor_name
            if appsheet_test_type:
                tr.test_type = appsheet_test_type
                tr.test_type_code = appsheet_test_type_code or tr.test_type_code
            if doctor_name or appsheet_test_type:
                session.add(tr)
                await session.commit()
                await session.refresh(tr)
            logfire.info(f"Found TestResult {tr.id} (status={tr.status}) for patient {patient_id}.")
            return tr

        # Multiple TRs — merge all into the LATEST one
        target_tr = test_results[0]
        merged_sources = {target_tr.source}

        for tr in test_results[1:]:
            merged_sources.add(tr.source)

            # Load LabValues from this older TR
            older_lvs = await session.execute(
                select(LabValue).where(LabValue.test_result_id == tr.id)
            )

            for lv in older_lvs.scalars().all():
                # Skip if this parameter_code already exists in target TR
                dup_check = await session.execute(
                    select(LabValue).where(
                        LabValue.test_result_id == target_tr.id,
                        LabValue.parameter_code == lv.parameter_code,
                    )
                )
                if dup_check.scalars().first() is not None:
                    logfire.info(
                        f"Skipping duplicate {lv.parameter_code} from TestResult {tr.id} "
                        f"(already in TestResult {target_tr.id})"
                    )
                    continue

                # Copy LabValue to target TR (create new, don't reparent — avoids cascade complexity)
                new_lv = LabValue(
                    test_result_id=target_tr.id,
                    parameter_code=lv.parameter_code,
                    parameter_name_es=lv.parameter_name_es,
                    raw_value=lv.raw_value,
                    numeric_value=lv.numeric_value,
                    unit=lv.unit,
                    reference_range=lv.reference_range,
                    flag=lv.flag,
                    machine_flag=lv.machine_flag,
                )
                session.add(new_lv)

            # Delete the old TR (cascade deletes its now-redundant LabValues)
            await session.delete(tr)

        # Update target TR source to reflect merged provenance
        target_tr.source = ",".join(sorted(merged_sources))

        # Recalculate flag counts based on ALL merged LabValues
        all_lvs = await session.execute(
            select(LabValue).where(LabValue.test_result_id == target_tr.id)
        )
        flags = [lv.flag for lv in all_lvs.scalars().all()]
        target_tr.flag_alto_count = flags.count("ALTO")
        target_tr.flag_normal_count = flags.count("NORMAL")
        target_tr.flag_bajo_count = flags.count("BAJO")

        # Propagar doctor_name desde el Patient al TestResult unificado
        if doctor_name and not target_tr.doctor_name:
            target_tr.doctor_name = doctor_name

        # Propagar test_type desde ExamOrder (o Patient.appsheet_test_type) al TestResult
        if appsheet_test_type:
            target_tr.test_type = appsheet_test_type
            target_tr.test_type_code = appsheet_test_type_code or target_tr.test_type_code

        await session.commit()
        await session.refresh(target_tr)

        logfire.info(
            f"Merged {len(test_results)} TestResults into TestResult {target_tr.id} "
            f"(sources: {target_tr.source}, params: {len(flags)}) for patient {patient_id}."
        )
        return target_tr

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
                batch_received_at = datetime.now(timezone.utc).isoformat()  # mismo timestamp para todo el batch
                for record in records:
                    # 'record' is a FujifilmReading object
                    process_fujifilm_message.send({
                        "internal_id": record.internal_id,
                        "patient_name": record.patient_name,
                        "parameter_code": record.parameter_code,
                        "raw_value": record.raw_value,
                        "source": PatientSource.LIS_FUJIFILM.value,
                        "received_at": batch_received_at
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

        # Check for latest TestResult
        from app.shared.models.test_result import TestResult
        from sqlmodel import select
        tr_stmt = select(TestResult.id).where(TestResult.patient_id == patient.id).order_by(TestResult.id.desc()).limit(1)
        tr_result = await session.execute(tr_stmt)
        latest_result_id = tr_result.scalar_one_or_none()

        # ── Look up active ExamOrders ─────────────────────────────────
        exam_orders_list: list[dict] = []
        orders = await self._exam_order_service.get_by_patient(patient.id, session)
        for order in orders:
            exam_orders_list.append({
                "id": order.id,
                "session_code": order.session_code,
                "exam_types": order.exam_types,
                "status": order.status,
            })

        patient_data = {
            "id": patient.id,
            "name": patient.name,
            "species": patient.species,
            "sex": patient.sex,
            "owner_name": patient.owner_name,
            "age_display": patient.age_display,
            "session_code": patient.session_code,
            "result_id": latest_result_id,
            "waiting_room_status": patient.waiting_room_status,
            "sources_received": sources_received,
            "exam_orders": exam_orders_list,
            "appsheet_test_type": patient.appsheet_test_type,
            "appsheet_test_type_code": patient.appsheet_test_type_code,
            "created_at": patient.created_at.isoformat() if patient.created_at else None,
            "updated_at": patient.updated_at.isoformat() if patient.updated_at else None,
            "source": patient.source,
            "normalized_name": patient.normalized_name,
            "normalized_owner": patient.normalized_owner,
        }
        return patient_data