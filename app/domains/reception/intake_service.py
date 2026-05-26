from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import select
from app.domains.reception.schemas import RawPatientInput, BaulResult, PatientSource, NormalizedPatient
from app.domains.reception.normalizer import parse_patient_string
from app.domains.reception.baul import BaulService, _normalize_for_comparison
from app.domains.patients.models import Patient
from app.shared.models.data_quarantine import DataQuarantine
from app.services.provenance_recorder import ProvenanceRecorder
from app.domains.reception.helpers import _sanitize_patient_age
import logfire


class PatientIntakeService:
    """Core patient intake logic: session_code lookup, temporal isolation,
    normalization, dedup, and creation.

    Extracted from ReceptionService.receive() as part of the Strangler Fig
    refactoring (PR #5). Zero behavioral change — verbatim copy.
    """

    def __init__(self):
        self._baul = BaulService()

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
