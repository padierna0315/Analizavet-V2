import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_get_editor_index(client: AsyncClient):
    response = await client.get("/modoeditor")
    # It will fail with 404 until we include the router in app/main.py
    assert response.status_code == 200
    assert "Editor de Estándares" in response.text

@pytest.mark.asyncio
async def test_get_editor_form(client: AsyncClient):
    response = await client.get("/modoeditor/form/RBC")
    assert response.status_code == 200
    assert 'name="name"' in response.text
    assert 'value="Eritrocitos"' in response.text

@pytest.mark.asyncio
async def test_save_parameter(client: AsyncClient):
    # Change RBC name to "Eritrocitos Modificado"
    payload = {
        "name": "Eritrocitos Modificado",
        "unit": "x10^6/µL",
        "canine_min": "5.65",
        "canine_max": "8.87",
        "feline_min": "6.54",
        "feline_max": "12.20"
    }
    response = await client.post("/modoeditor/save/RBC", data=payload)
    assert response.status_code == 200
    assert "Eritrocitos Modificado" in response.text
    
    # Verify it changed in VETERINARY_STANDARDS
    from clinical_standards import VETERINARY_STANDARDS
    assert VETERINARY_STANDARDS["RBC"]["name"] == "Eritrocitos Modificado"
    
    # Clean up: Reset to defaults
    await client.post("/modoeditor/reset")
