"""Tests for GET /auto/status endpoint — auto domain status.

Verifies JSON shape with patient counts, jornada entries,
and timestamp fields per spec AS-1.
"""

import pytest
from httpx import AsyncClient
from sqlmodel import select, delete

from app.domains.patients.models import Patient
from app.domains.jornada.service import append_to_jornada_log, clear_jornada_log


@pytest.fixture(autouse=True)
async def clean_auto_state(session):
    """Ensure clean DB and jornada log state between tests."""
    clear_jornada_log()
    await session.execute(delete(Patient))
    await session.commit()
    yield
    clear_jornada_log()
    await session.execute(delete(Patient))
    await session.commit()


@pytest.mark.asyncio
async def test_auto_status_with_data(client: AsyncClient, session):
    """GIVEN active patients and jornada entries
    WHEN GET /auto/status
    THEN correct counts are returned and timestamps are null."""
    # Seed an active patient
    p = Patient(
        name="Kitty",
        species="Felino",
        sex="Hembra",
        owner_name="Laura Cepeda",
        normalized_name="kitty",
        normalized_owner="laura cepeda",
        source="appsheet",
        waiting_room_status="active",
    )
    session.add(p)
    await session.commit()

    # Seed jornada entries
    append_to_jornada_log({
        "name": "Kitty",
        "species": "Felino",
        "owner": "Laura Cepeda",
        "doctor": "Dr. García",
        "test_type": "Perfil Básico",
        "test_type_code": "CHEM",
    })

    response = await client.get("/auto/status")
    assert response.status_code == 200
    data = response.json()

    assert data["patients_waiting_count"] == 1
    assert data["jornada_entries"] == 1
    assert data["last_sync_at"] is None
    assert data["last_reprocess_at"] is None


@pytest.mark.asyncio
async def test_auto_status_empty(client: AsyncClient):
    """GIVEN no patients and no jornada entries
    WHEN GET /auto/status
    THEN all counts are zero and timestamps are null."""
    response = await client.get("/auto/status")
    assert response.status_code == 200
    data = response.json()

    assert data["patients_waiting_count"] == 0
    assert data["jornada_entries"] == 0
    assert data["last_sync_at"] is None
    assert data["last_reprocess_at"] is None
