import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.appsheet import AppSheetService, AppSheetPatient

@pytest.mark.asyncio
async def test_fetch_active_patients_success():
    # Law 1: reference AppSheetService which doesn't exist yet
    mock_response_data = [
        {
            "Codigo_Corto": "A1",
            "Doctora": "Aura",
            "Categoria_Examen": "Examen de sangre",
            "Examen_Especifico": "Perfil Básico (PQ1)",
            "Nombre_Mascota": "Lucas",
            "Especie": "Felino",
            "Sexo": "Macho",
            "Edad_Numero": "13",
            "Edad_Unidad": "Años",
            "Nombre_Tutor": "Luz Bonolis Serna",
            "Raza": "Mestizo"
        }
    ]

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = mock_response_data
        mock_post.return_value = mock_response

        service = AppSheetService(api_key="test-key", app_id="test-id")
        patients = await service.fetch_active_patients()

        assert len(patients) == 1
        assert isinstance(patients[0], AppSheetPatient)
        assert patients[0].session_code == "A1"
        assert patients[0].name == "Lucas"
        assert patients[0].species == "Felino"
        assert patients[0].vet_name == "Aura"

@pytest.mark.asyncio
async def test_fetch_active_patients_with_rows_key():
    mock_response_data = {
        "Rows": [
            {
                "Codigo_Corto": "A2",
                "Doctora": "Aura",
                "Categoria_Examen": "Examen de sangre",
                "Examen_Especifico": "Perfil Básico (PQ1)",
                "Nombre_Mascota": "Sasha",
                "Especie": "Felino",
                "Sexo": "Hembra",
                "Edad_Numero": "2",
                "Edad_Unidad": "Años",
                "Nombre_Tutor": "Juan Perez",
                "Raza": "Persa"
            }
        ]
    }

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = mock_response_data
        mock_post.return_value = mock_response

        service = AppSheetService(api_key="test-key", app_id="test-id")
        patients = await service.fetch_active_patients()

        assert len(patients) == 1
        assert patients[0].session_code == "A2"
        assert patients[0].name == "Sasha"

@pytest.mark.asyncio
async def test_fetch_active_patients_empty():
    mock_response_data = []

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = mock_response_data
        mock_post.return_value = mock_response

        service = AppSheetService(api_key="test-key", app_id="test-id")
        patients = await service.fetch_active_patients()

        assert len(patients) == 0

@pytest.mark.asyncio
async def test_fetch_active_patients_error():
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Unauthorized", request=MagicMock(), response=mock_response
        )
        mock_post.return_value = mock_response

        service = AppSheetService(api_key="test-key", app_id="test-id")
        with pytest.raises(httpx.HTTPStatusError):
            await service.fetch_active_patients()
