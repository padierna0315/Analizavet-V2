import pytest
from httpx import AsyncClient
from app.main import app # Assuming your FastAPI app instance is named 'app' and is in main.py
from unittest.mock import patch, AsyncMock

@pytest.fixture(name="client")
async def client_fixture():
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client

@pytest.fixture
def mock_handle_uploaded_file():
    with patch("app.domains.reception.service.ReceptionService.handle_uploaded_file") as mock:
        mock.return_value = "test_upload_id_123" # Simulate a successful file upload and return an ID
        yield mock

@pytest.fixture(autouse=True)
def mock_get_upload_status():
    with patch("app.domains.reception.router.get_upload_status") as mock:
        yield mock

@pytest.mark.asyncio
async def test_handle_upload_success_returns_202_and_polling_html(client: AsyncClient, mock_handle_uploaded_file):
    response = await client.post(
        "/reception/upload",
        files={"file": ("test.hl7", b"MSH|...", "application/octet-stream")},
        data={"file_type": "ozelle"}
    )
    
    assert response.status_code == 202
    assert "hx-get=\"/reception/upload/test_upload_id_123/status\"" in response.text
    assert "hx-trigger=\"every 2s\"" in response.text
    assert "⏳ Procesando archivo..." in response.text
    mock_handle_uploaded_file.assert_called_once()

@pytest.mark.asyncio
async def test_handle_upload_returns_422_on_value_error(client: AsyncClient, mock_handle_uploaded_file):
    mock_handle_uploaded_file.side_effect = ValueError("Invalid file type")
    
    response = await client.post(
        "/reception/upload",
        files={"file": ("test.txt", b"some text", "text/plain")},
        data={"file_type": "invalid"}
    )
    
    assert response.status_code == 422
    assert "Invalid file type" in response.json()["detail"]

@pytest.mark.asyncio
async def test_get_upload_status_processing_returns_polling_html(client: AsyncClient, mock_get_upload_status):
    mock_get_upload_status.return_value = "processing"
    
    response = await client.get("/reception/upload/some_upload_id/status")
    
    assert response.status_code == 200
    assert "hx-get=\"/reception/upload/some_upload_id/status\"" in response.text
    assert "hx-trigger=\"every 2s\"" in response.text
    assert "⏳ Procesando archivo..." in response.text

@pytest.mark.asyncio
async def test_get_upload_status_complete_returns_success_html_and_trigger(client: AsyncClient, mock_get_upload_status):
    mock_get_upload_status.return_value = "complete:10"
    
    response = await client.get("/reception/upload/some_upload_id/status")
    
    assert response.status_code == 200
    assert "✅ 10 paciente(s) cargado(s)" in response.text
    assert "HX-Trigger" in response.headers
    assert response.headers["HX-Trigger"] == "refreshReceptionGrid"

@pytest.mark.asyncio
async def test_get_upload_status_error_returns_error_html(client: AsyncClient, mock_get_upload_status):
    mock_get_upload_status.return_value = "error:File corrupted"
    
    response = await client.get("/reception/upload/some_upload_id/status")
    
    assert response.status_code == 200
    assert "❌ Error: File corrupted" in response.text

@pytest.mark.asyncio
async def test_get_upload_status_not_found_returns_error_html(client: AsyncClient, mock_get_upload_status):
    mock_get_upload_status.return_value = None
    
    response = await client.get("/reception/upload/some_non_existent_id/status")
    
    assert response.status_code == 200
    assert "❌ Estado no encontrado (o expirado)" in response.text
