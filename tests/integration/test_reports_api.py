import pytest
from datetime import datetime, timezone
from httpx import AsyncClient

from tests.integration.test_taller_api import register_patient, make_lab_values


async def enrich_result(client: AsyncClient, patient_id: int) -> int:
    """Helper: enrich a test result and return result_id."""
    response = await client.post("/taller/enrich", json={
        "patient_id": patient_id,
        "species": "Felino",
        "test_type": "Hemograma",
        "test_type_code": "CBC",
        "source": "LIS_OZELLE",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "values": make_lab_values(),
    })
    assert response.status_code == 200
    return response.json()["test_result_id"]


# ── GET /reports/{id}/pdf ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pdf_returns_200(client: AsyncClient):
    """PDF endpoint returns 200 OK for a valid result_id."""
    patient_id = await register_patient(client)
    result_id = await enrich_result(client, patient_id)

    response = await client.get(f"/reports/{result_id}/pdf")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_pdf_content_type_is_application_pdf(client: AsyncClient):
    """PDF endpoint returns application/pdf content type."""
    patient_id = await register_patient(client)
    result_id = await enrich_result(client, patient_id)

    response = await client.get(f"/reports/{result_id}/pdf")
    assert response.headers["content-type"] == "application/pdf"


@pytest.mark.asyncio
async def test_pdf_content_disposition_filename(client: AsyncClient):
    """Content-Disposition header has correct filename format."""
    patient_id = await register_patient(client)
    result_id = await enrich_result(client, patient_id)

    response = await client.get(f"/reports/{result_id}/pdf")
    content_disp = response.headers.get("content-disposition", "")
    # Expected format: attachment; filename="Kitty_20260424_Hemograma.pdf"
    assert content_disp.startswith('attachment; filename="')
    assert content_disp.endswith('.pdf"')
    # Check the filename pattern: PatientName_Date_TestType.pdf
    assert "Kitty_" in content_disp
    assert "Hemograma" in content_disp


@pytest.mark.asyncio
async def test_pdf_not_found(client: AsyncClient):
    """PDF endpoint returns 404 for non-existent result_id."""
    response = await client.get("/reports/99999/pdf")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_pdf_response_is_non_empty_bytes(client: AsyncClient):
    """PDF response body is non-empty bytes (actual PDF content)."""
    patient_id = await register_patient(client)
    result_id = await enrich_result(client, patient_id)

    response = await client.get(f"/reports/{result_id}/pdf")
    assert len(response.content) > 0
    # PDF files start with %PDF
    assert response.content[:4] == b'%PDF'
