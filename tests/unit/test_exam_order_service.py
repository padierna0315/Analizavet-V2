"""Tests for ExamOrderService — creation, resolution, idempotency, status transitions."""

from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from app.domains.exam_order.models import ExamOrder
from app.domains.exam_order.service import ExamOrderService
from sqlmodel import select


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def service() -> ExamOrderService:
    return ExamOrderService()


@pytest.fixture
def sample_data_single() -> dict:
    return {
        "Codigo_Corto": "A1-20260501",
        "Examen_Especifico": "Perfil Básico",
        "patient_id": "1",
    }


@pytest.fixture
def sample_data_multi() -> dict:
    return {
        "Codigo_Corto": "B2-20260501",
        "Examen_Especifico": "Perfil Básico, BUN",
        "patient_id": "1",
    }


@pytest.fixture
def sample_data_fuzzy() -> dict:
    """'Basico Perfil' (reversed words) requires fuzzy token_sort_ratio to match."""
    return {
        "Codigo_Corto": "C3-20260501",
        "Examen_Especifico": "Basico Perfil",
        "patient_id": "1",
    }


@pytest.fixture
def sample_data_unknown() -> dict:
    """'Electrocardiograma' has no match in the catalog at all."""
    return {
        "Codigo_Corto": "D4-20260501",
        "Examen_Especifico": "Electrocardiograma",
        "patient_id": "1",
    }


# ── create_from_appsheet ─────────────────────────────────────────────────


class TestCreateFromAppSheet:
    """Tests for creating ExamOrder from AppSheet data."""

    @pytest.mark.asyncio
    async def test_single_exam(
        self, service: ExamOrderService, session: AsyncSession, sample_data_single: dict
    ):
        order = await service.create_from_appsheet(sample_data_single, session)

        assert order.id is not None
        assert order.session_code == "A1-20260501"
        assert order.patient_id == 1
        assert order.status == "pending"
        assert order.exam_types == ["CHEM_BASIC"]
        assert order.appsheet_row_id is None

    @pytest.mark.asyncio
    async def test_multi_exam(
        self, service: ExamOrderService, session: AsyncSession, sample_data_multi: dict
    ):
        order = await service.create_from_appsheet(sample_data_multi, session)

        assert order.session_code == "B2-20260501"
        assert order.exam_types == ["CHEM_BASIC"]
        # "BUN" is not in the catalog — should be silently skipped
        assert "BUN" not in order.exam_types

    @pytest.mark.asyncio
    async def test_fuzzy_match(
        self, service: ExamOrderService, session: AsyncSession, sample_data_fuzzy: dict
    ):
        """'Basico Perfil' (reversed words) should fuzzy-match via token_sort_ratio to CHEM_BASIC."""
        order = await service.create_from_appsheet(sample_data_fuzzy, session)

        assert order.session_code == "C3-20260501"
        assert order.exam_types == ["CHEM_BASIC"]

    @pytest.mark.asyncio
    async def test_unknown_exam(
        self, service: ExamOrderService, session: AsyncSession, sample_data_unknown: dict
    ):
        """Unknown exam types result in an empty exam_types list (don't crash)."""
        order = await service.create_from_appsheet(sample_data_unknown, session)

        assert order.session_code == "D4-20260501"
        assert order.exam_types == []
        assert order.status == "pending"

    @pytest.mark.asyncio
    async def test_idempotent_same_session_code_updates(
        self, service: ExamOrderService, session: AsyncSession, sample_data_single: dict
    ):
        order1 = await service.create_from_appsheet(sample_data_single, session)
        first_id = order1.id
        first_updated_at = order1.updated_at

        # Same session_code, different exam — should update existing
        updated_data = {
            "Codigo_Corto": "A1-20260501",
            "Examen_Especifico": "Hemograma",
            "patient_id": "1",
        }
        order2 = await service.create_from_appsheet(updated_data, session)

        assert order2.id == first_id  # Same record
        assert order2.exam_types == ["CBC"]  # Updated
        assert order2.updated_at >= first_updated_at  # Timestamp refreshed

    @pytest.mark.asyncio
    async def test_idempotent_same_session_code_twice(
        self, service: ExamOrderService, session: AsyncSession, sample_data_single: dict
    ):
        order1 = await service.create_from_appsheet(sample_data_single, session)
        order2 = await service.create_from_appsheet(sample_data_single, session)

        assert order2.id == order1.id
        # Verify only one record in DB
        stmt = select(ExamOrder).where(ExamOrder.session_code == "A1-20260501")
        result = await session.execute(stmt)
        rows = result.scalars().all()
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_missing_codigo_corto_raises(
        self, service: ExamOrderService, session: AsyncSession
    ):
        with pytest.raises(ValueError, match="missing Codigo_Corto"):
            await service.create_from_appsheet({"Examen_Especifico": "CBC"}, session)

    @pytest.mark.asyncio
    async def test_missing_patient_id_raises(
        self, service: ExamOrderService, session: AsyncSession
    ):
        with pytest.raises(ValueError, match="missing patient identifier"):
            await service.create_from_appsheet(
                {"Codigo_Corto": "X1-20260501", "Examen_Especifico": "CBC"},
                session,
            )

    @pytest.mark.asyncio
    async def test_with_appsheet_row_id(
        self, service: ExamOrderService, session: AsyncSession
    ):
        data = {
            "Codigo_Corto": "E5-20260501",
            "Examen_Especifico": "Uroanálisis",
            "patient_id": "1",
            "appsheet_row_id": "row_abc123",
        }
        order = await service.create_from_appsheet(data, session)
        assert order.appsheet_row_id == "row_abc123"


# ── resolve_exam_types ───────────────────────────────────────────────────


class TestResolveExamTypes:
    """Direct tests for the exam type resolution logic."""

    @pytest.mark.asyncio
    async def test_exact_match(self, service: ExamOrderService):
        codes = await service.resolve_exam_types("Perfil Básico")
        assert codes == ["CHEM_BASIC"]

    @pytest.mark.asyncio
    async def test_alias_match(self, service: ExamOrderService):
        codes = await service.resolve_exam_types("PQ1")
        assert codes == ["CHEM_BASIC"]

    @pytest.mark.asyncio
    async def test_fuzzy_match(self, service: ExamOrderService):
        """'Basico Perfil' (reversed words) should fuzzy-match via token_sort_ratio."""
        codes = await service.resolve_exam_types("Basico Perfil")
        assert codes == ["CHEM_BASIC"]

    @pytest.mark.asyncio
    async def test_unknown(self, service: ExamOrderService):
        codes = await service.resolve_exam_types("Nefrologia")
        assert codes == []

    @pytest.mark.asyncio
    async def test_empty_string(self, service: ExamOrderService):
        codes = await service.resolve_exam_types("")
        assert codes == []

    @pytest.mark.asyncio
    async def test_comma_separated(self, service: ExamOrderService):
        codes = await service.resolve_exam_types("Perfil Básico, Hemograma, Uroanálisis")
        assert codes == ["CHEM_BASIC", "CBC", "URINALYSIS"]

    @pytest.mark.asyncio
    async def test_mixed_known_and_unknown(self, service: ExamOrderService):
        codes = await service.resolve_exam_types("Hemograma, Tomografía")
        assert codes == ["CBC"]  # Tomografía skipped


# ── get_by_patient ───────────────────────────────────────────────────────


class TestGetByPatient:
    """Tests for retrieving ExamOrders by patient ID."""

    @pytest.mark.asyncio
    async def test_returns_orders_for_patient(
        self, service: ExamOrderService, session: AsyncSession
    ):
        o1 = ExamOrder(patient_id=1, session_code="A1-20260501")
        o2 = ExamOrder(patient_id=1, session_code="A2-20260501")
        o3 = ExamOrder(patient_id=2, session_code="B1-20260501")
        session.add_all([o1, o2, o3])
        await session.commit()

        results = await service.get_by_patient(1, session)
        assert len(results) == 2
        assert {r.session_code for r in results} == {"A1-20260501", "A2-20260501"}

    @pytest.mark.asyncio
    async def test_returns_empty_list_for_no_orders(
        self, service: ExamOrderService, session: AsyncSession
    ):
        results = await service.get_by_patient(999, session)
        assert results == []


# ── get_by_session_code ─────────────────────────────────────────────────


class TestGetBySessionCode:
    """Tests for retrieving a single ExamOrder by session code."""

    @pytest.mark.asyncio
    async def test_found(
        self, service: ExamOrderService, session: AsyncSession
    ):
        order = ExamOrder(patient_id=1, session_code="Z1-20260501")
        session.add(order)
        await session.commit()

        result = await service.get_by_session_code("Z1-20260501", session)
        assert result is not None
        assert result.id == order.id
        assert result.patient_id == 1

    @pytest.mark.asyncio
    async def test_not_found(
        self, service: ExamOrderService, session: AsyncSession
    ):
        result = await service.get_by_session_code("NONEXISTENT", session)
        assert result is None


# ── update_status ────────────────────────────────────────────────────────


class TestUpdateStatus:
    """Tests for status transitions — valid and invalid."""

    @pytest.mark.asyncio
    async def test_pending_to_partial(
        self, service: ExamOrderService, session: AsyncSession
    ):
        order = ExamOrder(patient_id=1, session_code="S1-20260501", status="pending")
        session.add(order)
        await session.commit()
        await session.refresh(order)

        updated = await service.update_status(order.id, "partial", session)
        assert updated.status == "partial"

    @pytest.mark.asyncio
    async def test_pending_to_complete(
        self, service: ExamOrderService, session: AsyncSession
    ):
        order = ExamOrder(patient_id=1, session_code="S2-20260501", status="pending")
        session.add(order)
        await session.commit()
        await session.refresh(order)

        updated = await service.update_status(order.id, "complete", session)
        assert updated.status == "complete"

    @pytest.mark.asyncio
    async def test_pending_to_cancelled(
        self, service: ExamOrderService, session: AsyncSession
    ):
        order = ExamOrder(patient_id=1, session_code="S3-20260501", status="pending")
        session.add(order)
        await session.commit()
        await session.refresh(order)

        updated = await service.update_status(order.id, "cancelled", session)
        assert updated.status == "cancelled"

    @pytest.mark.asyncio
    async def test_partial_to_complete(
        self, service: ExamOrderService, session: AsyncSession
    ):
        order = ExamOrder(patient_id=1, session_code="S4-20260501", status="partial")
        session.add(order)
        await session.commit()
        await session.refresh(order)

        updated = await service.update_status(order.id, "complete", session)
        assert updated.status == "complete"

    @pytest.mark.asyncio
    async def test_partial_to_cancelled(
        self, service: ExamOrderService, session: AsyncSession
    ):
        order = ExamOrder(patient_id=1, session_code="S5-20260501", status="partial")
        session.add(order)
        await session.commit()
        await session.refresh(order)

        updated = await service.update_status(order.id, "cancelled", session)
        assert updated.status == "cancelled"

    @pytest.mark.asyncio
    async def test_invalid_transition_raises(
        self, service: ExamOrderService, session: AsyncSession
    ):
        """complete → pending is not allowed."""
        order = ExamOrder(patient_id=1, session_code="S6-20260501", status="complete")
        session.add(order)
        await session.commit()
        await session.refresh(order)

        with pytest.raises(ValueError, match="terminal"):
            await service.update_status(order.id, "pending", session)

    @pytest.mark.asyncio
    async def test_invalid_transition_partial_to_pending(
        self, service: ExamOrderService, session: AsyncSession
    ):
        """partial → pending is not allowed."""
        order = ExamOrder(patient_id=1, session_code="S7-20260501", status="partial")
        session.add(order)
        await session.commit()
        await session.refresh(order)

        with pytest.raises(ValueError, match="Invalid transition"):
            await service.update_status(order.id, "pending", session)

    @pytest.mark.asyncio
    async def test_terminal_complete_rejects_any(
        self, service: ExamOrderService, session: AsyncSession
    ):
        order = ExamOrder(patient_id=1, session_code="S8-20260501", status="complete")
        session.add(order)
        await session.commit()
        await session.refresh(order)

        with pytest.raises(ValueError, match="terminal"):
            await service.update_status(order.id, "cancelled", session)

    @pytest.mark.asyncio
    async def test_terminal_cancelled_rejects_any(
        self, service: ExamOrderService, session: AsyncSession
    ):
        order = ExamOrder(patient_id=1, session_code="S9-20260501", status="cancelled")
        session.add(order)
        await session.commit()
        await session.refresh(order)

        with pytest.raises(ValueError, match="terminal"):
            await service.update_status(order.id, "pending", session)

    @pytest.mark.asyncio
    async def test_nonexistent_order_raises(
        self, service: ExamOrderService, session: AsyncSession
    ):
        with pytest.raises(ValueError, match="not found"):
            await service.update_status(99999, "complete", session)
