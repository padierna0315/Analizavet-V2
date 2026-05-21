import json
import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.appsheet import AppSheetService, AppSheetPatient
from app.shared.models.raw_data_log import RawDataSource

@pytest.mark.asyncio
async def test_fetch_active_patients_success():
    # Law 1: reference AppSheetService which doesn't exist yet
    mock_response_data = [
        {
            "Codigo_Corto": "A1",
            "Doctora": "Aura",
            "Categoria_Examen": "Examen de sangre",
            "Examen_Especifico": "Perfil Básico (PQ1)",
            "Nombre_Mascota": "A1 Lucas",
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
        assert patients[0].name == "A1 Lucas"
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
                "Nombre_Mascota": "A2 Sasha",
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
        assert patients[0].name == "A2 Sasha"

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


# ── Provenance recording hook tests (Task 2.1) ──────────────────────────


@pytest.mark.asyncio
async def test_fetch_with_session_records_provenance():
    """When session is provided, raw JSON is captured BEFORE parsing."""
    mock_response_data = [
        {
            "Codigo_Corto": "A1",
            "Doctora": "Aura",
            "Categoria_Examen": "Examen de sangre",
            "Examen_Especifico": "Perfil Básico (PQ1)",
            "Nombre_Mascota": "A1 Lucas",
            "Especie": "Felino",
            "Sexo": "Macho",
            "Edad_Numero": "13",
            "Edad_Unidad": "Años",
            "Nombre_Tutor": "Luz Bonolis Serna",
            "Raza": "Mestizo",
        }
    ]
    mock_session = MagicMock(spec=AsyncSession)

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = mock_response_data
        mock_post.return_value = mock_response

        with patch(
            "app.services.appsheet.ProvenanceRecorder.record_sync", new_callable=AsyncMock
        ) as mock_record:
            service = AppSheetService(api_key="test-key", app_id="test-id")
            patients = await service.fetch_active_patients(session=mock_session)

            # Fetch still works
            assert len(patients) == 1
            assert patients[0].session_code == "A1"

            # Provenance was recorded with source=appsheet
            mock_record.assert_called_once()
            call_kwargs = mock_record.call_args.kwargs
            assert call_kwargs["source"] == RawDataSource.APPSHEET
            assert call_kwargs["session"] is mock_session
            # Raw data is the JSON string of the response
            assert "Lucas" in call_kwargs["raw_data"]


@pytest.mark.asyncio
async def test_fetch_without_session_no_provenance():
    """When session is None, fetch works as before — no provenance call."""
    mock_response_data = [
        {
            "Codigo_Corto": "B2",
            "Doctora": "Aura",
            "Categoria_Examen": "",
            "Examen_Especifico": "",
            "Nombre_Mascota": "B2 Max",
            "Especie": "Canino",
            "Sexo": "Macho",
            "Edad_Numero": "5",
            "Edad_Unidad": "Años",
            "Nombre_Tutor": "Ana",
            "Raza": "Labrador",
        }
    ]

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = mock_response_data
        mock_post.return_value = mock_response

        with patch(
            "app.services.appsheet.ProvenanceRecorder.record_sync", new_callable=AsyncMock
        ) as mock_record:
            service = AppSheetService(api_key="test-key", app_id="test-id")
            patients = await service.fetch_active_patients()  # No session

            assert len(patients) == 1
            assert patients[0].name == "B2 Max"
            # Provenance was NOT called
            mock_record.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_provenance_failure_still_returns_patients():
    """When provenance recording raises, patients are still returned."""
    mock_response_data = [
        {
            "Codigo_Corto": "C3",
            "Doctora": "Aura",
            "Categoria_Examen": "",
            "Examen_Especifico": "",
            "Nombre_Mascota": "C3 Luna",
            "Especie": "Felino",
            "Sexo": "Hembra",
            "Edad_Numero": "1",
            "Edad_Unidad": "Año",
            "Nombre_Tutor": "Pedro",
            "Raza": "Siamés",
        }
    ]
    mock_session = MagicMock(spec=AsyncSession)

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = mock_response_data
        mock_post.return_value = mock_response

        with patch(
            "app.services.appsheet.ProvenanceRecorder.record_sync",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB failure"),
        ):
            service = AppSheetService(api_key="test-key", app_id="test-id")
            patients = await service.fetch_active_patients(session=mock_session)

            # Must still return patients despite recording failure
            assert len(patients) == 1
            assert patients[0].name == "C3 Luna"
            assert patients[0].session_code == "C3"


@pytest.mark.asyncio
async def test_fetch_empty_response_with_session_records_provenance():
    """Empty AppSheet response is still recorded as raw data."""
    mock_response_data = []
    mock_session = MagicMock(spec=AsyncSession)

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = mock_response_data
        mock_post.return_value = mock_response

        with patch(
            "app.services.appsheet.ProvenanceRecorder.record_sync", new_callable=AsyncMock
        ) as mock_record:
            service = AppSheetService(api_key="test-key", app_id="test-id")
            patients = await service.fetch_active_patients(session=mock_session)

            assert patients == []
            # Even empty responses are recorded
            mock_record.assert_called_once()
            assert mock_record.call_args.kwargs["source"] == RawDataSource.APPSHEET
