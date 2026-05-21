"""Tests for DataQuarantine SQLModel — model, enum, and DB roundtrip."""

from datetime import datetime, timezone

import pytest
from sqlmodel import SQLModel, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import pytest_asyncio

from app.shared.models.data_quarantine import DataQuarantine, QuarantineStatus


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def session():
    """In-memory SQLite session with tables created."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as s:
        yield s
    await engine.dispose()


# ── Enum tests (no DB) ────────────────────────────────────────────────────

class TestQuarantineStatusEnum:
    """QuarantineStatus enum validation."""

    def test_enum_values(self):
        assert QuarantineStatus.PENDING.value == "pending"
        assert QuarantineStatus.REVIEWED.value == "reviewed"
        assert QuarantineStatus.DISCARDED.value == "discarded"
        assert QuarantineStatus.FORCED.value == "forced"

    def test_enum_count(self):
        statuses = list(QuarantineStatus)
        assert len(statuses) == 4


# ── Model creation (no DB) ────────────────────────────────────────────────

class TestDataQuarantineCreation:
    """Pure model instantiation — no database needed."""

    def test_create_with_required_fields(self):
        now = datetime.now(timezone.utc)
        quarantine = DataQuarantine(
            source="ozelle",
            raw_data="MSH|^~\\&|...",
            received_at=now,
            rejection_reason="missing_code",
        )
        assert quarantine.source == "ozelle"
        assert "MSH" in quarantine.raw_data
        assert quarantine.received_at == now
        assert quarantine.rejection_reason == "missing_code"

    def test_default_id_is_none(self):
        quarantine = DataQuarantine(
            source="fujifilm",
            raw_data="PATIENT: KIARA",
            received_at=datetime.now(timezone.utc),
            rejection_reason="invalid_code",
        )
        assert quarantine.id is None

    def test_default_status_is_pending(self):
        quarantine = DataQuarantine(
            source="appsheet",
            raw_data='{"name": "KIARA"}',
            received_at=datetime.now(timezone.utc),
            rejection_reason="missing_code",
        )
        assert quarantine.status == "pending"

    def test_optional_fields_default_to_none(self):
        quarantine = DataQuarantine(
            source="ozelle",
            raw_data="RAW",
            received_at=datetime.now(timezone.utc),
            rejection_reason="missing_code",
        )
        assert quarantine.session_code is None
        assert quarantine.patient_id is None
        assert quarantine.processed_at is None

    def test_session_code_can_be_set(self):
        quarantine = DataQuarantine(
            source="ozelle",
            raw_data="RAW",
            received_at=datetime.now(timezone.utc),
            rejection_reason="missing_code",
            session_code="M5",
        )
        assert quarantine.session_code == "M5"

    def test_patient_id_can_be_set(self):
        quarantine = DataQuarantine(
            source="ozelle",
            raw_data="RAW",
            received_at=datetime.now(timezone.utc),
            rejection_reason="missing_code",
            patient_id=42,
        )
        assert quarantine.patient_id == 42

    def test_processed_at_can_be_set(self):
        now = datetime.now(timezone.utc)
        quarantine = DataQuarantine(
            source="ozelle",
            raw_data="RAW",
            received_at=datetime.now(timezone.utc),
            rejection_reason="missing_code",
            processed_at=now,
        )
        assert quarantine.processed_at == now

    def test_status_can_be_explicitly_set(self):
        quarantine = DataQuarantine(
            source="ozelle",
            raw_data="RAW",
            received_at=datetime.now(timezone.utc),
            rejection_reason="missing_code",
            status="reviewed",
        )
        assert quarantine.status == "reviewed"

    def test_tablename_matches_migration_target(self):
        assert DataQuarantine.__tablename__ == "dataquarantine"

    def test_large_raw_data_stored(self):
        large_payload = "X" * 50_000
        quarantine = DataQuarantine(
            source="fujifilm",
            raw_data=large_payload,
            received_at=datetime.now(timezone.utc),
            rejection_reason="temporal_mismatch",
        )
        assert len(quarantine.raw_data) == 50_000


# ── Database roundtrip ──────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestDataQuarantineDB:
    """Database round-trip tests."""

    async def test_create_and_retrieve(self, session: AsyncSession):
        now = datetime.now(timezone.utc)
        quarantine = DataQuarantine(
            source="ozelle",
            raw_data="MSH|^~\\&|LAB|...",
            received_at=now,
            rejection_reason="missing_code",
        )
        session.add(quarantine)
        await session.commit()
        await session.refresh(quarantine)

        assert quarantine.id is not None
        assert quarantine.source == "ozelle"
        assert quarantine.status == "pending"
        assert quarantine.session_code is None

    async def test_multiple_records(self, session: AsyncSession):
        now = datetime.now(timezone.utc)
        q1 = DataQuarantine(
            source="ozelle", raw_data="R1", received_at=now,
            rejection_reason="missing_code",
        )
        q2 = DataQuarantine(
            source="fujifilm", raw_data="R2", received_at=now,
            rejection_reason="invalid_code",
        )
        session.add_all([q1, q2])
        await session.commit()

        assert q1.id is not None
        assert q2.id is not None
        assert q1.id != q2.id

    async def test_query_by_status(self, session: AsyncSession):
        now = datetime.now(timezone.utc)
        q_pending = DataQuarantine(
            source="ozelle", raw_data="R1", received_at=now,
            rejection_reason="missing_code", status="pending",
        )
        q_reviewed = DataQuarantine(
            source="ozelle", raw_data="R2", received_at=now,
            rejection_reason="missing_code", status="reviewed",
        )
        session.add_all([q_pending, q_reviewed])
        await session.commit()

        stmt = select(DataQuarantine).where(DataQuarantine.status == "pending")
        result = await session.execute(stmt)
        pending = result.scalars().all()

        assert len(pending) == 1
        assert pending[0].raw_data == "R1"

    async def test_update_status(self, session: AsyncSession):
        now = datetime.now(timezone.utc)
        quarantine = DataQuarantine(
            source="ozelle", raw_data="R1", received_at=now,
            rejection_reason="missing_code",
        )
        session.add(quarantine)
        await session.commit()

        quarantine.status = "reviewed"
        quarantine.processed_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(quarantine)

        assert quarantine.status == "reviewed"
        assert quarantine.processed_at is not None
