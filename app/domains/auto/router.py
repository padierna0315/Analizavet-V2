"""Auto domain — headless operator status and control.

Provides GET /auto/status for the auto_mode.py polling loop
to monitor patient counts and jornada entries.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, func

from app.database import get_session
from app.domains.patients.models import Patient
from app.domains.jornada.service import read_jornada_log

router = APIRouter(prefix="/auto", tags=["Auto"])

_last_sync_at: str | None = None
_last_reprocess_at: str | None = None


def set_last_sync_at(iso_timestamp: str) -> None:
    """Record the last successful AppSheet sync timestamp."""
    global _last_sync_at
    _last_sync_at = iso_timestamp


@router.get("/status")
async def auto_status(session: AsyncSession = Depends(get_session)):
    """Return headless operator status counts.

    Returns JSON with:
    - patients_waiting_count: active patients in waiting room
    - jornada_entries: entries in the jornada session log
    - last_sync_at: ISO 8601 timestamp of last sync (or null)
    - last_reprocess_at: ISO 8601 timestamp of last reprocess (or null)
    """
    query = select(func.count(Patient.id)).where(
        Patient.waiting_room_status == "active"
    )
    result = await session.execute(query)
    patients_count = result.scalar() or 0

    entries = read_jornada_log()
    jornada_count = len(entries)

    return {
        "patients_waiting_count": patients_count,
        "jornada_entries": jornada_count,
        "last_sync_at": _last_sync_at,
        "last_reprocess_at": _last_reprocess_at,
    }
