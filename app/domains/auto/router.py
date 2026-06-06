"""Auto domain — headless operator status and control.

Provides GET /auto/status for the auto_mode.py polling loop
to monitor patient counts and jornada entries.
"""

import asyncio

import redis
import redis.asyncio as aioredis

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, func

from app.config import settings
from app.database import get_session
from app.domains.patients.models import Patient
from app.domains.jornada.service import read_jornada_log

router = APIRouter(prefix="/auto", tags=["Auto"])

REDIS_URL = getattr(settings, "REDIS_URL", "redis://localhost:6379/0")

_LAST_SYNC_KEY = "analizavet:auto:last_sync_at"

# Module-level singleton Redis clients with connection pooling and timeouts
_sync_redis: redis.Redis | None = None
_async_redis: aioredis.Redis | None = None


def _get_sync_redis() -> redis.Redis:
    """Return a singleton synchronous Redis client with timeouts."""
    global _sync_redis
    if _sync_redis is None:
        _sync_redis = redis.from_url(
            REDIS_URL,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
    return _sync_redis


def _get_async_redis() -> aioredis.Redis:
    """Return a singleton asynchronous Redis client with timeouts."""
    global _async_redis
    if _async_redis is None:
        _async_redis = aioredis.from_url(
            REDIS_URL,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
    return _async_redis


def set_last_sync_at(iso_timestamp: str) -> None:
    """Record the last successful AppSheet sync timestamp."""
    r = _get_sync_redis()
    r.set(_LAST_SYNC_KEY, iso_timestamp)


@router.get("/status")
async def auto_status(session: AsyncSession = Depends(get_session)):
    """Return headless operator status counts.

    Returns JSON with:
    - patients_waiting_count: active patients in waiting room
    - jornada_entries: entries in the jornada session log
    - last_sync_at: ISO 8601 timestamp of last sync (or null)
    """
    query = select(func.count(Patient.id)).where(
        Patient.waiting_room_status == "active"
    )
    result = await session.execute(query)
    patients_count = result.scalar() or 0

    entries = await asyncio.to_thread(read_jornada_log)
    jornada_count = len(entries)

    try:
        r = _get_async_redis()
        raw_sync = await r.get(_LAST_SYNC_KEY)
    except redis.ConnectionError:
        raw_sync = None

    return {
        "patients_waiting_count": patients_count,
        "jornada_entries": jornada_count,
        "last_sync_at": raw_sync.decode() if raw_sync else None,
    }
