import unicodedata
from datetime import datetime, timezone

import logfire
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.patients.models import Patient
from app.domains.reception.schemas import NormalizedPatient, BaulResult


def _normalize_for_comparison(text: str) -> str:
    """Lowercase + remove accents. For deduplication only, never displayed."""
    # NFD decomposes accented chars: "á" → "a" + combining accent
    nfd = unicodedata.normalize("NFD", text.lower())
    # Keep only ASCII chars (removes combining accents)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


class BaulService:
    """Patient deduplication service.
    
    Receives a NormalizedPatient, checks if they exist,
    creates if new, returns patient_id + whether it was created.
    """

    async def register(
        self,
        patient: NormalizedPatient,
        session: AsyncSession,
        session_code: str | None = None,
    ) -> BaulResult:
        """Register a patient. No duplicates ever.
        
        Uses (normalized_name, normalized_owner, species) as dedup key.
        If session_code is provided, it's stored for cross-source merging.
        """
        norm_name = _normalize_for_comparison(patient.name)
        norm_owner = _normalize_for_comparison(patient.owner_name)

        # Check if patient already exists
        existing = await self._find_existing(
            session, norm_name, norm_owner, patient.species
        )

        if existing:
            # Update timestamp to track last seen
            existing.updated_at = datetime.now(timezone.utc)
            # Set session_code if provided and not already set
            if session_code and not existing.session_code:
                existing.session_code = session_code
            session.add(existing)
            await session.commit()
            await session.refresh(existing)
            
            logfire.info(
                f"Paciente existente: {patient.name} ({patient.species}) "
                f"- Tutor: {patient.owner_name} [id={existing.id}]"
            )
            return BaulResult(
                patient_id=existing.id,
                created=False,
                patient=patient,
            )

        # Create new patient
        db_patient = Patient(
            name=patient.name,
            species=patient.species,
            sex=patient.sex,
            owner_name=patient.owner_name,
            has_age=patient.has_age,
            age_value=patient.age_value,
            age_unit=patient.age_unit,
            age_display=patient.age_display,
            source=patient.source.value,
            normalized_name=norm_name,
            normalized_owner=norm_owner,
            session_code=session_code,
        )
        session.add(db_patient)
        await session.commit()
        await session.refresh(db_patient)

        logfire.info(
            f"Nuevo paciente: {patient.name} ({patient.species}) "
            f"- Tutor: {patient.owner_name} [id={db_patient.id}]"
        )
        return BaulResult(
            patient_id=db_patient.id,
            created=True,
            patient=patient,
        )

    async def _find_existing(
        self,
        session: AsyncSession,
        normalized_name: str,
        normalized_owner: str,
        species: str,
    ) -> Patient | None:
        result = await session.execute(
            select(Patient).where(
                Patient.normalized_name == normalized_name,
                Patient.normalized_owner == normalized_owner,
                Patient.species == species,
            )
        )
        return result.scalars().first()