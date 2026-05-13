"""Tests for ExamOrder SQLModel — creation, defaults, JSON serialization."""

from datetime import datetime

import pytest
from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import pytest_asyncio

from app.domains.exam_order.models import ExamOrder


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as s:
        yield s
    await engine.dispose()


# ── Model creation (no DB) ───────────────────────────────────────────────


class TestExamOrderCreation:
    """Pure model instantiation — no database needed."""

    def test_create_with_required_fields(self):
        order = ExamOrder(patient_id=1, session_code="A1-20260501")
        assert order.patient_id == 1
        assert order.session_code == "A1-20260501"

    def test_default_status_is_pending(self):
        order = ExamOrder(patient_id=1, session_code="A1-20260501")
        assert order.status == "pending"

    def test_default_exam_types_is_empty_list(self):
        order = ExamOrder(patient_id=1, session_code="A1-20260501")
        assert order.exam_types == []

    def test_default_appsheet_row_id_is_none(self):
        order = ExamOrder(patient_id=1, session_code="A1-20260501")
        assert order.appsheet_row_id is None

    def test_default_id_is_none(self):
        order = ExamOrder(patient_id=1, session_code="A1-20260501")
        assert order.id is None

    def test_timestamps_are_set_on_creation(self):
        order = ExamOrder(patient_id=1, session_code="A1-20260501")
        assert isinstance(order.created_at, datetime)
        assert isinstance(order.updated_at, datetime)

    def test_exam_types_assigned_as_list(self):
        order = ExamOrder(
            patient_id=1,
            session_code="A1-20260501",
            exam_types=["CHEM_BASIC", "CBC"],
        )
        assert order.exam_types == ["CHEM_BASIC", "CBC"]
        assert len(order.exam_types) == 2

    def test_exam_types_mutable(self):
        order = ExamOrder(patient_id=1, session_code="A1-20260501")
        order.exam_types.append("URINALYSIS")
        assert order.exam_types == ["URINALYSIS"]

    def test_status_can_be_set(self):
        order = ExamOrder(patient_id=1, session_code="A1-20260501", status="complete")
        assert order.status == "complete"

    def test_status_accepts_all_valid_values(self):
        for status in ("pending", "partial", "complete", "cancelled"):
            order = ExamOrder(
                patient_id=1, session_code="A1-20260501", status=status
            )
            assert order.status == status

    def test_appsheet_row_id_can_be_set(self):
        order = ExamOrder(
            patient_id=1,
            session_code="A1-20260501",
            appsheet_row_id="row_abc123",
        )
        assert order.appsheet_row_id == "row_abc123"

    def test_session_code_persists(self):
        order = ExamOrder(patient_id=1, session_code="G2-20260501")
        assert order.session_code == "G2-20260501"


# ── Database integration ─────────────────────────────────────────────────


@pytest.mark.asyncio
class TestExamOrderDB:
    """Database round-trip tests."""

    async def test_create_and_retrieve(self, session: AsyncSession):
        order = ExamOrder(patient_id=1, session_code="A1-20260501")
        session.add(order)
        await session.commit()
        await session.refresh(order)

        assert order.id is not None
        assert order.patient_id == 1
        assert order.session_code == "A1-20260501"
        assert order.status == "pending"
        assert order.exam_types == []
        assert order.created_at is not None
        assert order.updated_at is not None

    async def test_exam_types_stored_as_json(self, session: AsyncSession):
        order = ExamOrder(
            patient_id=1,
            session_code="B2-20260501",
            exam_types=["CHEM_BASIC", "CBC", "URINALYSIS"],
        )
        session.add(order)
        await session.commit()
        await session.refresh(order)

        assert order.exam_types == ["CHEM_BASIC", "CBC", "URINALYSIS"]

    async def test_appsheet_row_id_roundtrip(self, session: AsyncSession):
        order = ExamOrder(
            patient_id=2,
            session_code="C3-20260501",
            appsheet_row_id="appsheet_007",
        )
        session.add(order)
        await session.commit()
        await session.refresh(order)

        assert order.appsheet_row_id == "appsheet_007"

    async def test_status_roundtrip(self, session: AsyncSession):
        order = ExamOrder(
            patient_id=1, session_code="D4-20260501", status="complete"
        )
        session.add(order)
        await session.commit()
        await session.refresh(order)

        assert order.status == "complete"

    async def test_multiple_exam_orders(self, session: AsyncSession):
        """Verify multiple orders can coexist."""
        o1 = ExamOrder(patient_id=1, session_code="A1-20260501")
        o2 = ExamOrder(patient_id=2, session_code="B2-20260501")
        o3 = ExamOrder(patient_id=1, session_code="C3-20260501")
        session.add_all([o1, o2, o3])
        await session.commit()

        assert o1.id is not None
        assert o2.id is not None
        assert o3.id is not None
        assert o1.id != o2.id
        assert o1.patient_id == 1
        assert o2.patient_id == 2
