"""Integration tests for the Jornada (/jornada/resumen) endpoint — flat JSON log mode."""

import pytest
from httpx import AsyncClient

from app.domains.jornada.service import (
    append_to_jornada_log,
    read_jornada_log,
    clear_jornada_log,
)


# ── Fixture to clean the jornada log between tests ───────────────────────────

@pytest.fixture(autouse=True)
def clean_jornada_log_fixture():
    """Ensure the jornada log is cleared before and after each test."""
    clear_jornada_log()
    yield
    clear_jornada_log()


# ── GET /jornada/resumen ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_log_returns_no_report(client: AsyncClient):
    """When the jornada log is empty, the endpoint returns a no-report message."""
    response = await client.get("/jornada/resumen")
    assert response.status_code == 200
    assert "No hay reportes generados" in response.text


@pytest.mark.asyncio
async def test_single_entry_produces_report(client: AsyncClient):
    """A single entry in the log produces a jornada report with the correct category."""
    append_to_jornada_log({
        "name": "Kitty",
        "species": "Felino",
        "owner": "Laura Cepeda",
        "doctor": "Dr. García",
        "test_type": "Perfil Básico",
        "test_type_code": "CHEM",
    })

    response = await client.get("/jornada/resumen")
    assert response.status_code == 200

    assert "🐾 Reporte de jornada" in response.text
    assert "Perfiles básicos" in response.text
    assert "Kitty" in response.text
    assert "Laura Cepeda" in response.text
    assert "Dr. García" in response.text
    assert "Total: 1 reportes generados" in response.text


@pytest.mark.asyncio
async def test_multiple_entries_multiple_categories(client: AsyncClient):
    """Entries with different test_type_code appear in different categories."""
    append_to_jornada_log({
        "name": "Kitty", "species": "Felino", "owner": "Laura Cepeda",
        "doctor": "Dr. García", "test_type": "Perfil Básico", "test_type_code": "CHEM",
    })
    append_to_jornada_log({
        "name": "Rocky", "species": "Canino", "owner": "Juan Pérez",
        "doctor": "Dr. García", "test_type": "Coprológico", "test_type_code": "COPROSC",
    })

    response = await client.get("/jornada/resumen")
    assert response.status_code == 200

    assert "Perfiles básicos" in response.text
    assert "Coprológicos" in response.text
    assert "Kitty" in response.text
    assert "Rocky" in response.text
    assert "Total: 2 reportes generados" in response.text


@pytest.mark.asyncio
async def test_coprologico_seriado_detected(client: AsyncClient):
    """Coprológico with 'seriado' in test_type goes to the seriados category."""
    append_to_jornada_log({
        "name": "Kitty", "species": "Felino", "owner": "Laura Cepeda",
        "doctor": "Dr. García", "test_type": "Coprológico seriado",
        "test_type_code": "COPROSC",
    })

    response = await client.get("/jornada/resumen")
    assert response.status_code == 200

    assert "Coprológicos seriados" in response.text
    assert "Total: 1 reportes generados" in response.text


@pytest.mark.asyncio
async def test_citoquimico_category(client: AsyncClient):
    """CITO test_type_code entries go to the Citoquímicos category."""
    append_to_jornada_log({
        "name": "Rocky", "species": "Canino", "owner": "Juan Pérez",
        "doctor": "Dra. López", "test_type": "Citoquímico de orina",
        "test_type_code": "CITO",
    })

    response = await client.get("/jornada/resumen")
    assert response.status_code == 200

    assert "Citoquímicos" in response.text
    assert "Rocky" in response.text
    assert "Total: 1 reportes generados" in response.text


@pytest.mark.asyncio
async def test_response_headers(client: AsyncClient):
    """Response has correct content-type and content-disposition headers."""
    append_to_jornada_log({
        "name": "Kitty", "species": "Felino", "owner": "Laura Cepeda",
        "doctor": "Dr. García", "test_type": "Perfil Básico", "test_type_code": "CHEM",
    })

    response = await client.get("/jornada/resumen")
    assert response.status_code == 200

    content_type = response.headers.get("content-type", "")
    assert "text/plain" in content_type
    assert "charset=utf-8" in content_type

    content_disp = response.headers.get("content-disposition", "")
    assert content_disp.startswith("attachment")
    assert "resumen-jornada.txt" in content_disp


@pytest.mark.asyncio
async def test_log_is_cleared_after_report(client: AsyncClient):
    """After calling the endpoint, the jornada log should be cleared."""
    append_to_jornada_log({
        "name": "Kitty", "species": "Felino", "owner": "Laura Cepeda",
        "doctor": "Dr. García", "test_type": "Perfil Básico", "test_type_code": "CHEM",
    })

    response = await client.get("/jornada/resumen")
    assert response.status_code == 200

    # The log should be empty now
    remaining = read_jornada_log()
    assert len(remaining) == 0, f"Expected empty log after report, got {len(remaining)} entries"
