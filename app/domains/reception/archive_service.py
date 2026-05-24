from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update as sa_update
from sqlmodel import select
from app.domains.patients.models import Patient
import logfire


class PatientArchiveService:
    """Handles soft-archive operations via waiting_room_status flag."""

    async def archive_all_active(self, session: AsyncSession) -> int:
        """Set waiting_room_status='archived' for all active patients.

        Returns the number of patients archived.
        """
        stmt = (
            sa_update(Patient)
            .where(Patient.waiting_room_status == "active")
            .values(waiting_room_status="archived", updated_at=datetime.now(timezone.utc))
        )
        result = await session.execute(stmt)
        await session.commit()

        count = result.rowcount if hasattr(result, "rowcount") else 0
        logfire.info(f"Archived {count} patients (active → archived)")
        return count

    async def restore_all_archived(self, session: AsyncSession) -> int:
        """Set waiting_room_status='active' for all archived patients.

        Returns the number of patients restored.
        """
        stmt = (
            sa_update(Patient)
            .where(Patient.waiting_room_status == "archived")
            .values(waiting_room_status="active", updated_at=datetime.now(timezone.utc))
        )
        result = await session.execute(stmt)
        await session.commit()

        count = result.rowcount if hasattr(result, "rowcount") else 0
        logfire.info(f"Restored {count} patients (archived → active)")
        return count

    async def restore_single_archived(self, patient_id: int, session: AsyncSession) -> bool:
        """Set a single patient's status back to 'active'.

        Returns True if the patient was found and updated, False if not found.
        Idempotent: if already active, still returns True.
        """
        patient = await session.get(Patient, patient_id)
        if not patient:
            return False

        patient.waiting_room_status = "active"
        patient.updated_at = datetime.now(timezone.utc)
        session.add(patient)
        await session.commit()
        logfire.info(f"Restored patient {patient_id} (→ active)")
        return True

    async def get_archived_patients(self, session: AsyncSession) -> list[dict]:
        """Get all archived patients formatted for display."""
        from app.shared.models.test_result import TestResult

        query = (
            select(Patient)
            .where(Patient.waiting_room_status == "archived")
            .order_by(Patient.updated_at.desc())
        )
        result = await session.execute(query)
        patients = result.scalars().all()

        patients_data = []
        for patient in patients:
            # Get latest TestResult id for this patient
            tr_query = (
                select(TestResult.id)
                .where(TestResult.patient_id == patient.id)
                .order_by(TestResult.id.desc())
                .limit(1)
            )
            tr_result = await session.execute(tr_query)
            latest_result_id = tr_result.scalar_one_or_none()

            patients_data.append({
                "id": patient.id,
                "name": patient.name,
                "species": patient.species,
                "sex": patient.sex,
                "owner_name": patient.owner_name,
                "age_display": patient.age_display,
                "session_code": patient.session_code,
                "waiting_room_status": patient.waiting_room_status,
                "sources_received": list(patient.sources_received or []),
                "appsheet_test_type": patient.appsheet_test_type,
                "appsheet_test_type_code": patient.appsheet_test_type_code,
                "result_id": latest_result_id,
                "created_at": patient.created_at.isoformat() if patient.created_at else None,
                "updated_at": patient.updated_at.isoformat() if patient.updated_at else None,
                "source": patient.source,
            })

        return patients_data
