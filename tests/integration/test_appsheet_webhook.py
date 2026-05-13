"""Integration tests for the full AppSheet webhook flow.

Tests end-to-end: receive webhook payload → create ExamOrder(s) → verify in DB.
Uses the shared client fixture which sets up an in-memory SQLite database.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.domains.patients.models import Patient
from app.domains.exam_order.models import ExamOrder


@pytest.mark.asyncio
async def test_full_webhook_flow(
    client: AsyncClient, session: AsyncSession
):
    """Receive webhook payload → create ExamOrder → verify in DB.

    This test simulates a realistic AppSheet webhook call with two rows:
    one for a blood chemistry panel and one for a coproscopic exam.
    """
    # Arrange: create patients that match the webhook data
    patient1 = Patient(
        name="Lucas",
        species="Felino",
        sex="Macho",
        owner_name="Luz",
        source="APPSHEET",
        breed="Mestizo",
        has_age=True,
        age_value=13,
        age_unit="años",
        age_display="13 años",
        normalized_name="lucas",
        normalized_owner="luz",
        session_code="A1-20260501",
    )
    patient2 = Patient(
        name="Luna",
        species="Felino",
        sex="Hembra",
        owner_name="Ana Torres",
        source="APPSHEET",
        breed="Mestizo",
        has_age=True,
        age_value=3,
        age_unit="años",
        age_display="3 años",
        normalized_name="luna",
        normalized_owner="ana torres",
        session_code="B2-20260501",
    )
    session.add_all([patient1, patient2])
    await session.commit()
    await session.refresh(patient1)
    await session.refresh(patient2)

    # Act: send the webhook payload
    response = await client.post(
        "/api/appsheet/webhook",
        json=[
            {
                "Codigo_Corto": "A1-20260501",
                "Examen_Especifico": "Perfil Básico",
                "Paciente_ID": str(patient1.id),
            },
            {
                "Codigo_Corto": "B2-20260501",
                "Examen_Especifico": "Coprológico",
                "Paciente_ID": str(patient2.id),
            },
        ],
    )

    # Assert: HTTP response
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["created"] == 2
    assert data["updated"] == 0
    assert data["errors"] == 0

    # Assert: verify ExamOrders in DB
    stmt1 = select(ExamOrder).where(ExamOrder.session_code == "A1-20260501")
    result1 = await session.execute(stmt1)
    order1 = result1.scalar_one_or_none()
    assert order1 is not None, "ExamOrder for A1-20260501 was not created"
    assert order1.patient_id == patient1.id
    assert order1.exam_types == ["CHEM_BASIC"]
    assert order1.status == "pending"

    stmt2 = select(ExamOrder).where(ExamOrder.session_code == "B2-20260501")
    result2 = await session.execute(stmt2)
    order2 = result2.scalar_one_or_none()
    assert order2 is not None, "ExamOrder for B2-20260501 was not created"
    assert order2.patient_id == patient2.id
    assert order2.exam_types == ["COPROSC_SINGLE"]
    assert order2.status == "pending"

    # Verify exactly 2 ExamOrders were created (one per session_code)
    stmt_all = select(ExamOrder).where(
        ExamOrder.session_code.in_(["A1-20260501", "B2-20260501"])
    )
    all_orders = await session.execute(stmt_all)
    assert len(list(all_orders.scalars().all())) == 2


@pytest.mark.asyncio
async def test_webhook_idempotent_flow(
    client: AsyncClient, session: AsyncSession
):
    """Sending the same webhook twice should create only one ExamOrder.

    The second call should update the existing order (idempotent by session_code).
    """
    # Arrange: create a patient
    patient = Patient(
        name="Rocky",
        species="Canino",
        sex="Macho",
        owner_name="Juan Pérez",
        source="APPSHEET",
        breed="Mestizo",
        has_age=True,
        age_value=4,
        age_unit="años",
        age_display="4 años",
        normalized_name="rocky",
        normalized_owner="juan perez",
        session_code="C3-20260501",
    )
    session.add(patient)
    await session.commit()
    await session.refresh(patient)

    payload = [
        {
            "Codigo_Corto": "C3-20260501",
            "Examen_Especifico": "Hemograma",
            "Paciente_ID": str(patient.id),
        }
    ]

    # Act: first call creates
    r1 = await client.post("/api/appsheet/webhook", json=payload)
    assert r1.json()["created"] == 1
    assert r1.json()["updated"] == 0

    # Second call updates (same session_code)
    r2 = await client.post("/api/appsheet/webhook", json=payload)
    assert r2.json()["created"] == 0
    assert r2.json()["updated"] == 1

    # Assert: only one row in DB
    stmt = select(ExamOrder).where(ExamOrder.session_code == "C3-20260501")
    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    assert len(rows) == 1
    assert rows[0].exam_types == ["CBC"]
    assert rows[0].patient_id == patient.id


@pytest.mark.asyncio
async def test_webhook_with_appsheet_row_id(
    client: AsyncClient, session: AsyncSession
):
    """Webhook rows with a Row_ID should store it as appsheet_row_id."""
    patient = Patient(
        name="Milo",
        species="Canino",
        sex="Macho",
        owner_name="Carlos",
        source="APPSHEET",
        breed="Mestizo",
        has_age=True,
        age_value=2,
        age_unit="años",
        age_display="2 años",
        normalized_name="milo",
        normalized_owner="carlos",
        session_code="D4-20260501",
    )
    session.add(patient)
    await session.commit()
    await session.refresh(patient)

    response = await client.post(
        "/api/appsheet/webhook",
        json=[
            {
                "Codigo_Corto": "D4-20260501",
                "Examen_Especifico": "Uroanálisis",
                "Paciente_ID": str(patient.id),
                "Row_ID": "appsheet_row_xyz789",
            }
        ],
    )

    assert response.status_code == 200
    stmt = select(ExamOrder).where(ExamOrder.session_code == "D4-20260501")
    result = await session.execute(stmt)
    order = result.scalar_one()
    assert order.appsheet_row_id == "appsheet_row_xyz789"
