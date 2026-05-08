from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.database import get_session
from app.config import settings
import redis.asyncio as aioredis

router = APIRouter()


@router.get("/health")
async def health_check(session: AsyncSession = Depends(get_session)):
    """Comprehensive health check for the whole system."""
    status = {
        "status": "ok",
        "version": "2.0.0",
        "database": "unknown",
        "redis": "unknown"
    }

    # 1. Check Database
    try:
        await session.execute(text("SELECT 1"))
        status["database"] = "ok"
    except Exception as e:
        status["status"] = "error"
        status["database"] = f"error: {e}"

    # 2. Check Redis (Dramatiq Broker)
    redis_url = getattr(settings, "REDIS_URL", "redis://localhost:6379/0")
    try:
        r = aioredis.from_url(redis_url)
        await r.ping()
        status["redis"] = "ok"
        await r.close()
    except Exception as e:
        status["status"] = "error"
        status["redis"] = f"error: {e}"

    return status
