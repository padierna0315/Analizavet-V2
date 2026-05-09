import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch
from app.services.appsheet import AppSheetPatient

@pytest.mark.asyncio
async def test_appsheet_sync_endpoint_success(client: AsyncClient):
    mock_patients = [
        AppSheetPatient(
            Codigo_Corto="A1",
            Doctora="Aura",
            Categoria_Examen="E",
            Examen_Especifico="S",
            Nombre_Mascota="Lucas",
            Especie="Felino",
            Sexo="Macho",
            Edad_Numero="13",
            Edad_Unidad="Años",
            Nombre_Tutor="Luz",
            Raza="M"
        )
    ]
    
    with patch("app.services.appsheet.AppSheetService.fetch_active_patients", new_callable=AsyncMock) as mock_fetch:
        mock_post_sync = AsyncMock(return_value=1)
        mock_fetch.return_value = mock_patients
        
        with patch("app.domains.reception.service.ReceptionService.sync_from_appsheet", new_callable=AsyncMock) as mock_sync:
            mock_sync.return_value = 1
            
            response = await client.post("/reception/appsheet/sync")
            
            assert response.status_code == 200
            assert "1 paciente(s) sincronizado(s)" in response.text
            assert "HX-Trigger" in response.headers
            assert "refreshReceptionGrid" in response.headers["HX-Trigger"]
