"""
Quarantine Reprocessing Actor — processes quarantined machine data
after AppSheet confirms the patient.

Triggered by AppSheetSyncService._link_quarantined_items() after
a patient is confirmed.
"""

import dramatiq
import logfire
from datetime import datetime, timezone

from sqlmodel import select
from app.database import AsyncSessionLocal
from app.domains.reception.schemas import RawPatientInput, PatientSource
from app.domains.reception.intake_service import PatientIntakeService
from app.shared.models.data_quarantine import DataQuarantine


@dramatiq.actor(max_retries=3, time_limit=60000)
def reprocess_quarantined(quarantine_id: int):
    """Dramatiq actor entry point — wraps async reprocessing."""
    import anyio
    anyio.run(_async_reprocess_quarantined, quarantine_id)


async def _async_reprocess_quarantined(quarantine_id: int):
    """Reprocess a quarantined item now that the patient is confirmed.

    1. Fetch the quarantine record by ID.
    2. Reconstruct RawPatientInput from stored raw_data/source/session_code.
    3. Call PatientIntakeService.receive() — now finds confirmed patient.
    4. Log result — errors are logged, not re-raised.
    """
    async with AsyncSessionLocal() as session:
        try:
            stmt = select(DataQuarantine).where(DataQuarantine.id == quarantine_id)
            result = await session.execute(stmt)
            quarantine = result.scalar_one_or_none()

            if quarantine is None:
                logfire.warning(
                    f"Quarantine reprocess: record {quarantine_id} not found"
                )
                return

            logfire.info(
                f"Reprocessing quarantined item {quarantine_id}: "
                f"source={quarantine.source}, session_code={quarantine.session_code}"
            )

            # Reconstruct the original input
            source_enum = PatientSource(quarantine.source)
            raw_input = RawPatientInput(
                raw_string=quarantine.raw_data,
                session_code=quarantine.session_code,
                source=source_enum,
                received_at=quarantine.received_at,
            )

            # Run intake — the patient should now be confirmed
            intake = PatientIntakeService()
            baul_result = await intake.receive(raw_input, session)

            logfire.info(
                f"Quarantine reprocess complete: item={quarantine_id}, "
                f"patient_id={baul_result.patient_id}, "
                f"created={baul_result.created}"
            )

        except Exception as e:
            logfire.error(
                f"Quarantine reprocess failed for item {quarantine_id}: {e}",
                _exc_info=True,
            )
            # Don't re-raise — Dramatiq will retry if needed
