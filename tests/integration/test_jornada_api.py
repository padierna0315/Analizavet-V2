"""Integration tests for the Jornada (/jornada/resumen) endpoint."""

import os
import time
import pytest
from datetime import datetime, timezone
from httpx import AsyncClient

from app.domains.jornada.service import SESSION_MARKER
from tests.integration.test_taller_api import register_patient, make_lab_values


async def enrich_with_code(client: AsyncClient, patient_id: int, test_type_code: str, test_type: str) -> int:
    """Helper: enrich a test result with specific test_type_code and return result_id."""
    response = await client.post("/taller/enrich", json={
        "patient_id": patient_id,
        "species": "Felino",
        "test_type": test_type,
        "test_type_code": test_type_code,
        "source": "LIS_OZELLE",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "values": make_lab_values(),
    })
    assert response.status_code == 200
    return response.json()["test_result_id"]


# ── Fixtures for marker file management ────────────────────────────────────────


@pytest.fixture(autouse=True)
def clean_marker():
    """Ensure the session marker file does not exist before each test."""
    if os.path.exists(SESSION_MARKER):
        os.remove(SESSION_MARKER)
    yield
    # Clean up after test
    if os.path.exists(SESSION_MARKER):
        os.remove(SESSION_MARKER)


# ── GET /jornada/resumen ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_marker(client: AsyncClient):
    """When no marker file exists, the endpoint returns the inactive message."""
    response = await client.get("/jornada/resumen")
    assert response.status_code == 200
    assert "No hay sesión activa" in response.text


@pytest.mark.asyncio
async def test_empty_session(client: AsyncClient):
    """When marker exists but no results, all categories show (Sin resultados)."""
    marker_ts = time.time() - 3600  # 1 hour ago
    with open(SESSION_MARKER, "w") as f:
        f.write(str(marker_ts))

    response = await client.get("/jornada/resumen")
    assert response.status_code == 200
    assert "🐾 Reporte de jornada — Huellas Lab" in response.text
    # Should show "No hay reportes generados" since there are no results
    assert "No hay reportes generados" in response.text


@pytest.mark.asyncio
async def test_populated_session(client: AsyncClient):
    """Results created after the session marker appear in the correct category."""
    marker_ts = time.time() - 3600  # 1 hour ago
    with open(SESSION_MARKER, "w") as f:
        f.write(str(marker_ts))

    # Create a CHEM (Perfil Básico) result
    patient_id = await register_patient(client)
    await enrich_with_code(client, patient_id, "CHEM", "Perfil Básico")

    response = await client.get("/jornada/resumen")
    assert response.status_code == 200

    # Should show the perfiles category with data
    assert "🔬 Perfiles básicos del día" in response.text
    # Kitty was registered with the helper
    assert "kitty" in response.text.lower() or "Kitty" in response.text
    # The total should be 1
    assert "✅ Total: 1 reportes generados" in response.text


@pytest.mark.asyncio
async def test_populated_session_multiple_categories(client: AsyncClient):
    """Results with different test_type_code appear in different categories."""
    marker_ts = time.time() - 3600  # 1 hour ago
    with open(SESSION_MARKER, "w") as f:
        f.write(str(marker_ts))

    # Create a CHEM result
    patient_chem = await register_patient(client)
    await enrich_with_code(client, patient_chem, "CHEM", "Perfil Básico")

    # Create a COPROSC result (Coprologico - not seriado)
    patient_copro = await register_patient(client)
    await enrich_with_code(client, patient_copro, "COPROSC", "Coprológico")

    response = await client.get("/jornada/resumen")
    assert response.status_code == 200

    # Should show both categories
    assert "🔬 Perfiles básicos del día" in response.text
    assert "🦠 Coprológicos" in response.text
    # Note: both enrich calls use the same deduplicated patient,
    # so there are 2 CHEM + 1 COPROSC = 3 total results
    assert "✅ Total: 3 reportes generados" in response.text


@pytest.mark.asyncio
async def test_response_headers(client: AsyncClient):
    """Response has correct content-type and content-disposition headers."""
    # Create a marker to get a non-error response
    marker_ts = time.time() - 3600
    with open(SESSION_MARKER, "w") as f:
        f.write(str(marker_ts))

    response = await client.get("/jornada/resumen")
    assert response.status_code == 200

    # Check content-type
    content_type = response.headers.get("content-type", "")
    assert "text/plain" in content_type
    assert "charset=utf-8" in content_type

    # Check content-disposition
    content_disp = response.headers.get("content-disposition", "")
    assert content_disp.startswith("attachment")
    assert "resumen-jornada.txt" in content_disp
