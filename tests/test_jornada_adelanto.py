"""Integration tests for GET /jornada/adelanto — read-only report endpoint.

Verifies:
- Same format as /jornada/resumen
- Does NOT clear the jornada log
- Response header X-Jornada-Mode: HASTA-AHORA
"""

import pytest
from httpx import AsyncClient

from app.domains.jornada.service import (
    append_to_jornada_log,
    read_jornada_log,
    clear_jornada_log,
)


@pytest.fixture(autouse=True)
def clean_jornada_log_fixture():
    """Ensure the jornada log is cleared before and after each test."""
    clear_jornada_log()
    yield
    clear_jornada_log()


@pytest.mark.asyncio
async def test_adelanto_returns_same_format_as_resumen(client: AsyncClient):
    """GIVEN entries in the jornada log
    WHEN adelanto is called
    THEN the response contains the same report format as resumen."""
    append_to_jornada_log({
        "name": "Kitty",
        "species": "Felino",
        "owner": "Laura Cepeda",
        "doctor": "Dr. García",
        "test_type": "Perfil Básico",
        "test_type_code": "CHEM",
    })

    response = await client.get("/jornada/adelanto")
    assert response.status_code == 200
    assert "🐾 Reporte de jornada" in response.text
    assert "Perfiles básicos" in response.text
    assert "Kitty" in response.text
    assert "Laura Cepeda" in response.text
    assert "Dr. García" in response.text


@pytest.mark.asyncio
async def test_adelanto_does_not_clear_log(client: AsyncClient):
    """GIVEN 3 entries in the jornada log
    WHEN adelanto is called twice
    THEN both responses contain the same 3 entries AND log keeps 3 entries."""
    for i in range(3):
        append_to_jornada_log({
            "name": f"Pet{i}",
            "species": "Canino",
            "owner": f"Owner{i}",
            "doctor": "Dra. López",
            "test_type": "Coprológico",
            "test_type_code": "COPROSC",
        })

    # First call
    response1 = await client.get("/jornada/adelanto")
    assert response1.status_code == 200
    assert "Total: 3 reportes generados" in response1.text

    # Second call — must return same entries
    response2 = await client.get("/jornada/adelanto")
    assert response2.status_code == 200
    assert "Total: 3 reportes generados" in response2.text

    # Log must NOT be cleared
    remaining = read_jornada_log()
    assert len(remaining) == 3, (
        f"Expected 3 entries after adelanto calls, got {len(remaining)}"
    )


@pytest.mark.asyncio
async def test_adelanto_empty_log(client: AsyncClient):
    """GIVEN empty jornada log
    WHEN adelanto is called
    THEN response reads no-report message."""
    response = await client.get("/jornada/adelanto")
    assert response.status_code == 200
    assert "No hay reportes generados" in response.text


@pytest.mark.asyncio
async def test_adelanto_header_x_jornada_mode(client: AsyncClient):
    """Response includes X-Jornada-Mode: HASTA-AHORA header."""
    append_to_jornada_log({
        "name": "Rocky",
        "species": "Canino",
        "owner": "Juan Pérez",
        "doctor": "Dr. García",
        "test_type": "Citoquímico de orina",
        "test_type_code": "CITO",
    })

    response = await client.get("/jornada/adelanto")
    assert response.status_code == 200
    assert response.headers.get("X-Jornada-Mode") == "HASTA-AHORA"
