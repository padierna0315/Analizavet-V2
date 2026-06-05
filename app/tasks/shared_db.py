"""Shared synchronous database engine for Dramatiq actors.

Prevents SQLite deadlock by ensuring all background task modules
use a single connection pool.
"""

from sqlmodel import create_engine
from app.config import settings

sync_engine = create_engine(settings.DATABASE_URL, echo=False)
