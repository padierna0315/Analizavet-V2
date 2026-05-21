"""DataQuarantine — holding area for rejected lab data.

Stores rejected payloads with full raw data, reason, and admin review state.
All foreign keys are nullable with ON DELETE SET NULL to avoid cascading deletes.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import Column, ForeignKey, Integer
from sqlmodel import Field, SQLModel


class QuarantineStatus(str, Enum):
    """Lifecycle state of a quarantined record."""

    PENDING = "pending"
    REVIEWED = "reviewed"
    DISCARDED = "discarded"
    FORCED = "forced"


class DataQuarantine(SQLModel, table=True):
    """Safe holding area for rejected lab data.

    Inserted automatically on gatekeeper rejection. Preserves the original
    payload for admin review. Admins can force-match a code, discard junk,
    or retry after editing raw data.
    """

    __tablename__ = "dataquarantine"

    id: Optional[int] = Field(default=None, primary_key=True)

    # Where the data came from: "ozelle" | "fujifilm" | "appsheet"
    source: str

    # Full original payload — JSON, HL7, or plain text (Text column)
    raw_data: str

    # When the external system sent/generated the data
    received_at: datetime

    # Why it was rejected: "missing_code" | "invalid_code" | "temporal_mismatch"
    rejection_reason: str

    # Lifecycle state — defaults to pending
    status: str = Field(default=QuarantineStatus.PENDING.value, index=True)

    # Timestamps
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    processed_at: Optional[datetime] = Field(default=None)

    # Admin-assigned code (set during force-match)
    session_code: Optional[str] = Field(default=None, index=True)

    # Nullable FK: linked patient after force-match, SET NULL on patient deletion
    patient_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("patient.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
