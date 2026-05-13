"""Integration tests for the ExamOrder API endpoints.

Tests cover the webhook, patient/session lookups, and status transitions
using the HTTP client against the running FastAPI app.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.domains.patients.models import Patient
from app.domains.exam_order.models import ExamOrder


# ── Helpers ───────────────────────────────────────────────────────────────


async def _create_patient(session: AsyncSession, **overrides) -> Patient:
    """Create and commit a minimal Patient record for tests."""
    patient = Patient(
        name=overrides.get("name", "TestPatient"),
        species=overrides.get("species", "Felino"),
        sex=overrides.get("sex", "Hembra"),
        owner_name=overrides.get("owner_name", "Test Owner"),
        source=overrides.get("source", "APPSHEET"),
        breed=overrides.get("breed", "Mestizo"),
        has_age=overrides.get("has_age", True),
        age_value=overrides.get("age_value", 3),
        age_unit=overrides.get("age_unit", "años"),
        age_display=overrides.get("age_display", "3 años"),
        normalized_name=overrides.get("normalized_name", "testpatient"),
        normalized_owner=overrides.get("normalized_owner", "test owner"),
        session_code=overrides.get("session_code"),
    )
    session.add(patient)
    await session.commit()
    await session.refresh(patient)
    return patient


# ── POST /api/appsheet/webhook ────────────────────────────────────────────


class TestAppSheetWebhook:
    """Tests for the AppSheet webhook endpoint."""

    @pytest.mark.asyncio
    async def test_webhook_creates_exam_order(
        self, client: AsyncClient, session: AsyncSession
    ):
        """A valid webhook payload should create an ExamOrder."""
        patient = await _create_patient(session, session_code="WH1-20260501")

        response = await client.post(
            "/api/appsheet/webhook",
            json=[
                {
                    "Codigo_Corto": "WH1-20260501",
                    "Examen_Especifico": "Perfil Básico",
                    "Paciente_ID": str(patient.id),
                }
            ],
        )

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["created"] == 1
        assert data["updated"] == 0
        assert data["errors"] == 0

    @pytest.mark.asyncio
    async def test_webhook_multi_exam(
        self, client: AsyncClient, session: AsyncSession
    ):
        """Webhook with multiple exams in a single row should resolve all."""
        patient = await _create_patient(session, session_code="WH2-20260501")

        response = await client.post(
            "/api/appsheet/webhook",
            json=[
                {
                    "Codigo_Corto": "WH2-20260501",
                    "Examen_Especifico": "Hemograma, Uroanálisis, Perfil Básico",
                    "Paciente_ID": str(patient.id),
                }
            ],
        )

        assert response.status_code == 200
        data = response.json()
        assert data["created"] == 1
        assert data["errors"] == 0

        # Verify in DB
        stmt = select(ExamOrder).where(
            ExamOrder.session_code == "WH2-20260501"
        )
        result = await session.execute(stmt)
        order = result.scalar_one()
        assert order.exam_types == ["CBC", "URINALYSIS", "CHEM_BASIC"]

    @pytest.mark.asyncio
    async def test_webhook_unknown_exam_does_not_crash(
        self, client: AsyncClient, session: AsyncSession
    ):
        """Unknown exam types should be handled gracefully (logged, skipped)."""
        patient = await _create_patient(session, session_code="WH3-20260501")

        response = await client.post(
            "/api/appsheet/webhook",
            json=[
                {
                    "Codigo_Corto": "WH3-20260501",
                    "Examen_Especifico": "Electrocardiograma, Radiografía",
                    "Paciente_ID": str(patient.id),
                }
            ],
        )

        assert response.status_code == 200
        data = response.json()
        assert data["created"] == 1
        assert data["errors"] == 0

        # Order should have been created with empty exam_types
        stmt = select(ExamOrder).where(
            ExamOrder.session_code == "WH3-20260501"
        )
        result = await session.execute(stmt)
        order = result.scalar_one()
        assert order.exam_types == []

    @pytest.mark.asyncio
    async def test_webhook_idempotent(
        self, client: AsyncClient, session: AsyncSession
    ):
        """Calling webhook twice with same session_code should update, not duplicate."""
        patient = await _create_patient(session, session_code="WH4-20260501")

        # First call
        r1 = await client.post(
            "/api/appsheet/webhook",
            json=[
                {
                    "Codigo_Corto": "WH4-20260501",
                    "Examen_Especifico": "Perfil Básico",
                    "Paciente_ID": str(patient.id),
                }
            ],
        )
        assert r1.json()["created"] == 1
        assert r1.json()["updated"] == 0

        # Second call with different exam
        r2 = await client.post(
            "/api/appsheet/webhook",
            json=[
                {
                    "Codigo_Corto": "WH4-20260501",
                    "Examen_Especifico": "Hemograma",
                    "Paciente_ID": str(patient.id),
                }
            ],
        )
        assert r2.json()["created"] == 0
        assert r2.json()["updated"] == 1

        # Only one row in DB
        stmt = select(ExamOrder).where(
            ExamOrder.session_code == "WH4-20260501"
        )
        result = await session.execute(stmt)
        rows = list(result.scalars().all())
        assert len(rows) == 1
        # Exam types should be the updated ones
        assert rows[0].exam_types == ["CBC"]

    @pytest.mark.asyncio
    async def test_webhook_missing_codigo_corto_logged(
        self, client: AsyncClient, session: AsyncSession
    ):
        """Rows missing Codigo_Corto should be counted as errors and skipped."""
        response = await client.post(
            "/api/appsheet/webhook",
            json=[
                {
                    "Examen_Especifico": "Hemograma",
                    "Paciente_ID": "1",
                }
            ],
        )

        assert response.status_code == 200
        data = response.json()
        assert data["created"] == 0
        assert data["updated"] == 0
        assert data["errors"] == 1

    @pytest.mark.asyncio
    async def test_webhook_partial_batch_failure(
        self, client: AsyncClient, session: AsyncSession
    ):
        """One bad row should not prevent other rows from being processed."""
        patient = await _create_patient(session, session_code="WH5-20260501")

        response = await client.post(
            "/api/appsheet/webhook",
            json=[
                {
                    # Missing Codigo_Corto — will be an error
                    "Examen_Especifico": "Hemograma",
                    "Paciente_ID": str(patient.id),
                },
                {
                    "Codigo_Corto": "WH5-20260501",
                    "Examen_Especifico": "Uroanálisis",
                    "Paciente_ID": str(patient.id),
                },
            ],
        )

        assert response.status_code == 200
        data = response.json()
        assert data["created"] == 1
        assert data["errors"] == 1


# ── GET /exam-orders/patient/{patient_id} ─────────────────────────────────


class TestGetByPatient:
    """Tests for retrieving ExamOrders by patient ID."""

    @pytest.mark.asyncio
    async def test_get_orders_by_patient(
        self, client: AsyncClient, session: AsyncSession
    ):
        patient = await _create_patient(session, session_code="GP1-20260501")
        patient2 = await _create_patient(
            session,
            name="Other",
            normalized_name="other",
            session_code="GP2-20260501",
        )

        # Create orders
        for sc in ["GP1-20260501", "GP1-20260502"]:
            order = ExamOrder(patient_id=patient.id, session_code=sc)
            session.add(order)
        # Order for other patient
        order = ExamOrder(patient_id=patient2.id, session_code="GP2-20260501")
        session.add(order)
        await session.commit()

        response = await client.get(f"/exam-orders/patient/{patient.id}")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        session_codes = {o["session_code"] for o in data}
        assert session_codes == {"GP1-20260501", "GP1-20260502"}

    @pytest.mark.asyncio
    async def test_get_orders_no_patient(
        self, client: AsyncClient, session: AsyncSession
    ):
        """Patient with no orders returns empty list."""
        response = await client.get("/exam-orders/patient/999")
        assert response.status_code == 200
        assert response.json() == []


# ── GET /exam-orders/session/{session_code} ───────────────────────────────


class TestGetBySessionCode:
    """Tests for retrieving ExamOrder by session code."""

    @pytest.mark.asyncio
    async def test_get_by_session_code_found(
        self, client: AsyncClient, session: AsyncSession
    ):
        patient = await _create_patient(session, session_code="SC1-20260501")
        order = ExamOrder(
            patient_id=patient.id,
            session_code="SC1-20260501",
            exam_types=["CHEM_BASIC"],
        )
        session.add(order)
        await session.commit()

        response = await client.get("/exam-orders/session/SC1-20260501")
        assert response.status_code == 200
        data = response.json()
        assert data["session_code"] == "SC1-20260501"
        assert data["exam_types"] == ["CHEM_BASIC"]
        assert data["patient_id"] == patient.id

    @pytest.mark.asyncio
    async def test_get_by_session_code_not_found(
        self, client: AsyncClient, session: AsyncSession
    ):
        response = await client.get("/exam-orders/session/NONEXISTENT")
        assert response.status_code == 404


# ── PATCH /exam-orders/{order_id}/status ──────────────────────────────────


class TestUpdateStatus:
    """Tests for updating ExamOrder status via API."""

    @pytest.mark.asyncio
    async def test_update_status_valid(
        self, client: AsyncClient, session: AsyncSession
    ):
        patient = await _create_patient(session, session_code="ST1-20260501")
        order = ExamOrder(
            patient_id=patient.id,
            session_code="ST1-20260501",
            status="pending",
        )
        session.add(order)
        await session.commit()
        await session.refresh(order)

        response = await client.patch(
            f"/exam-orders/{order.id}/status",
            json={"status": "partial"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "partial"

    @pytest.mark.asyncio
    async def test_update_status_invalid_transition(
        self, client: AsyncClient, session: AsyncSession
    ):
        patient = await _create_patient(session, session_code="ST2-20260501")
        order = ExamOrder(
            patient_id=patient.id,
            session_code="ST2-20260501",
            status="complete",  # Terminal state
        )
        session.add(order)
        await session.commit()
        await session.refresh(order)

        response = await client.patch(
            f"/exam-orders/{order.id}/status",
            json={"status": "pending"},
        )
        assert response.status_code == 400
        assert "terminal" in response.text.lower()

    @pytest.mark.asyncio
    async def test_update_status_nonexistent_order(
        self, client: AsyncClient, session: AsyncSession
    ):
        response = await client.patch(
            "/exam-orders/99999/status",
            json={"status": "complete"},
        )
        assert response.status_code == 400
