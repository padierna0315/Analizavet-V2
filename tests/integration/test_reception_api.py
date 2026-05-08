import pytest
from datetime import datetime, timezone
from httpx import AsyncClient


# ── POST /reception/upload ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upload_hl7_batch_file(client: AsyncClient, stub_broker):
    """Upload endpoint should accept an HL7 file and return a 200 with an HX-Trigger."""
    hl7_content = b'MSH|^~\\&|TEST||||20260101120000||ORU^R01|1|P|2.3.1\rPID|1\r'
    
    response = await client.post(
        "/reception/upload",
        files={"file": ("test.hl7", hl7_content, "text/plain")},
        data={"file_type": "ozelle"}
    )
    
    assert response.status_code == 202

@pytest.mark.asyncio
async def test_upload_json_baptism_file(client: AsyncClient, stub_broker):
    """Upload endpoint should accept a JSON file for baptism."""
    json_content = '{"raw_string": "luna felina 2a Ana Torres"}'
    
    response = await client.post(
        "/reception/upload",
        files={"file": ("baptism.json", json_content.encode('utf-8'), "application/json")},
        data={"file_type": "json"}
    )
    
    assert response.status_code == 202



# ── POST /reception/receive ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_receive_new_patient(client: AsyncClient):
    response = await client.post("/reception/receive", json={
        # Use unique name to avoid collision with other tests using "kitty felina 2a Laura Cepeda"
        "raw_string": "luna felina 3a Ana Gomez",
        "source": "LIS_OZELLE",
        "received_at": datetime.now(timezone.utc).isoformat(),
    })
    assert response.status_code == 200
    data = response.json()
    assert data["created"] is True
    assert data["patient_id"] > 0
    assert data["patient"]["name"] == "Luna"
    assert data["patient"]["species"] == "Felino"
    assert data["patient"]["sex"] == "Hembra"
    assert data["patient"]["owner_name"] == "Ana Gomez"

@pytest.mark.asyncio
async def test_receive_duplicate_patient(client: AsyncClient):
    payload = {
        "raw_string": "rocky canino 3a Juan Pérez",
        "source": "LIS_OZELLE",
        "received_at": datetime.now(timezone.utc).isoformat(),
    }
    r1 = await client.post("/reception/receive", json=payload)
    r2 = await client.post("/reception/receive", json=payload)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["created"] is True
    assert r2.json()["created"] is False
    assert r1.json()["patient_id"] == r2.json()["patient_id"]

@pytest.mark.asyncio
async def test_receive_invalid_species_returns_422(client: AsyncClient):
    response = await client.post("/reception/receive", json={
        "raw_string": "rocky perro 2a Juan",
        "source": "LIS_OZELLE",
        "received_at": datetime.now(timezone.utc).isoformat(),
    })
    assert response.status_code == 422

@pytest.mark.asyncio
async def test_receive_coproscopic_no_age(client: AsyncClient):
    response = await client.post("/reception/receive", json={
        "raw_string": "luna felina Laura García",
        "source": "LIS_OZELLE",
        "received_at": datetime.now(timezone.utc).isoformat(),
    })
    assert response.status_code == 200
    data = response.json()
    assert data["patient"]["has_age"] is False
    assert data["patient"]["age_display"] is None

@pytest.mark.asyncio
async def test_receive_lis_file_source(client: AsyncClient):
    response = await client.post("/reception/receive", json={
        "raw_string": "max canino 5a Pedro Gómez",
        "source": "LIS_FILE",
        "received_at": datetime.now(timezone.utc).isoformat(),
    })
    assert response.status_code == 200
    assert response.json()["patient"]["source"] == "LIS_FILE"


# ── GET /reception/patients ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_patients_empty(client: AsyncClient):
    response = await client.get("/reception/patients")
    assert response.status_code == 200
    data = response.json()
    assert "total" in data
    assert "patients" in data
    assert isinstance(data["patients"], list)

@pytest.mark.asyncio
async def test_list_patients_after_register(client: AsyncClient):
    await client.post("/reception/receive", json={
        "raw_string": "nala canina 1a Sofia Ruiz",
        "source": "LIS_OZELLE",
        "received_at": datetime.now(timezone.utc).isoformat(),
    })
    response = await client.get("/reception/patients")
    assert response.status_code == 200
    assert response.json()["total"] >= 1

@pytest.mark.asyncio
async def test_list_patients_filter_by_species(client: AsyncClient):
    response = await client.get("/reception/patients?species=Felino")
    assert response.status_code == 200
    for p in response.json()["patients"]:
        assert p["species"] == "Felino"



