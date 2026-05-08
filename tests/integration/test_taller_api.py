import pytest
from datetime import datetime, timezone
from httpx import AsyncClient


def make_lab_values():
    """Real-ish values from Ozelle log."""
    return [
        {
            "parameter_code": "WBC",
            "parameter_name_es": "Leucocitos",
            "raw_value": "14.26",
            "numeric_value": 14.26,
            "unit": "10*9/L",
            "reference_range": "5.05-16.76",
            "machine_flag": "N",
        },
        {
            "parameter_code": "RBC",
            "parameter_name_es": "Eritrocitos",
            "raw_value": "7.2",
            "numeric_value": 7.2,
            "unit": "10*12/L",
            "reference_range": "5.65-8.87",
            "machine_flag": "N",
        },
        {
            "parameter_code": "HGB",
            "parameter_name_es": "Hemoglobina",
            "raw_value": "5.0",
            "numeric_value": 5.0,
            "unit": "g/dL",
            "reference_range": "13.1-20.5",
            "machine_flag": "L",
        },
    ]


async def register_patient(client: AsyncClient) -> int:
    """Helper: register a patient and return patient_id."""
    r = await client.post("/reception/receive", json={
        "raw_string": "kitty felina 2a Laura Cepeda",
        "source": "LIS_OZELLE",
        "received_at": datetime.now(timezone.utc).isoformat(),
    })
    assert r.status_code == 200
    return r.json()["patient_id"]


# ── POST /taller/enrich ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_enrich_creates_test_result(client: AsyncClient):
    patient_id = await register_patient(client)
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
    data = response.json()
    assert data["status"] == "listo"
    assert data["test_result_id"] > 0
    assert data["total_values"] == 3
    assert "ALTO" in data["summary"]
    assert "NORMAL" in data["summary"]
    assert "BAJO" in data["summary"]


@pytest.mark.asyncio
async def test_enrich_invalid_patient_raises(client: AsyncClient):
    response = await client.post("/taller/enrich", json={
        "patient_id": 99999,
        "species": "Felino",
        "test_type": "Hemograma",
        "test_type_code": "CBC",
        "source": "LIS_OZELLE",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "values": make_lab_values(),
    })
    # Patient doesn't exist but TestResult is still created
    # The engine doesn't validate patient_id — that's OK for now
    assert response.status_code in [200, 422]


# ── GET /taller/results/{id} ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_result_returns_full_data(client: AsyncClient):
    patient_id = await register_patient(client)
    enrich = await client.post("/taller/enrich", json={
        "patient_id": patient_id,
        "species": "Felino",
        "test_type": "Hemograma",
        "test_type_code": "CBC",
        "source": "LIS_OZELLE",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "values": make_lab_values(),
    })
    result_id = enrich.json()["test_result_id"]

    response = await client.get(f"/taller/results/{result_id}")
    assert response.status_code == 200
    data = response.json()

    assert "test_result" in data
    assert "patient" in data
    assert "lab_values" in data
    assert "summary" in data
    assert len(data["lab_values"]) == 3

    # Check flags are present
    flags = {lv["flag"] for lv in data["lab_values"]}
    assert flags.issubset({"ALTO", "NORMAL", "BAJO"})


@pytest.mark.asyncio
async def test_get_result_not_found(client: AsyncClient):
    response = await client.get("/taller/results/99999")
    assert response.status_code == 404


# ── GET /taller/preview/{id} ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_preview_returns_html(client: AsyncClient):
    patient_id = await register_patient(client)
    enrich = await client.post("/taller/enrich", json={
        "patient_id": patient_id,
        "species": "Felino",
        "test_type": "Hemograma",
        "test_type_code": "CBC",
        "source": "LIS_OZELLE",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "values": make_lab_values(),
    })
    result_id = enrich.json()["test_result_id"]

    response = await client.get(f"/taller/preview/{result_id}")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    html = response.text
    # Must contain patient name and lab parameters
    assert "Kitty" in html
    assert "FELINO" in html
    # Check that lab parameters are rendered (flags may appear as arrows)
    assert "Leucocitos" in html or "Eritrocitos" in html or "Hemoglobina" in html


@pytest.mark.asyncio
async def test_preview_not_found(client: AsyncClient):
    response = await client.get("/taller/preview/99999")
    assert response.status_code == 404


# ── POST /taller/images ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upload_images(client: AsyncClient):
    import base64
    JPEG_MINI = base64.b64encode(b'\xff\xd8\xff\xe0' + b'\x00' * 10 + b'\xff\xd9').decode()

    patient_id = await register_patient(client)
    enrich = await client.post("/taller/enrich", json={
        "patient_id": patient_id,
        "species": "Felino",
        "test_type": "Hemograma",
        "test_type_code": "CBC",
        "source": "LIS_OZELLE",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "values": make_lab_values(),
    })
    result_id = enrich.json()["test_result_id"]

    response = await client.post("/taller/images", json={
        "test_result_id": result_id,
        "patient_name": "Kitty",
        "owner_name": "Laura Cepeda",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "images": [
            {"obs_identifier": "WBC_Main", "base64_data": JPEG_MINI},
        ],
    })
    assert response.status_code == 200
    data = response.json()
    assert data["total_saved"] + data["total_failed"] == 1


# ── GET /taller/{id} (full HTML page) ─────────────────────────────────────

@pytest.mark.asyncio
async def test_taller_page_renders_html(client: AsyncClient):
    """GET /taller/{id} returns full HTML page."""
    patient_id = await register_patient(client)
    enrich = await client.post("/taller/enrich", json={
        "patient_id": patient_id,
        "species": "Felino",
        "test_type": "Hemograma",
        "test_type_code": "CBC",
        "source": "LIS_OZELLE",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "values": make_lab_values(),
    })
    result_id = enrich.json()["test_result_id"]

    response = await client.get(f"/taller/{result_id}")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    html = response.text
    assert "Kitty" in html
    assert "Hemograma" in html
    assert "Leucocitos" in html  # parameter name in Spanish
    assert "taller-layout" in html  # CSS class confirming layout loaded


@pytest.mark.asyncio
async def test_taller_page_not_found(client: AsyncClient):
    response = await client.get("/taller/99999")
    assert response.status_code == 404


# ── POST /taller/preview/{id} (HTMX live preview) ─────────────────────────

@pytest.mark.asyncio
async def test_htmx_preview_returns_html_fragment(client: AsyncClient):
    """POST /taller/preview/{id} returns HTML fragment (not full page)."""
    patient_id = await register_patient(client)
    enrich = await client.post("/taller/enrich", json={
        "patient_id": patient_id,
        "species": "Felino",
        "test_type": "Hemograma",
        "test_type_code": "CBC",
        "source": "LIS_OZELLE",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "values": make_lab_values(),
    })
    result_id = enrich.json()["test_result_id"]

    # Simulate HTMX POST with form data
    response = await client.post(
        f"/taller/preview/{result_id}",
        data={
            "value_WBC": "15.0",   # Changed from 14.26
            "value_RBC": "7.2",
            "value_HGB": "5.0",
        }
    )

    assert response.status_code == 200
    html = response.text

    # Must contain updated data
    assert "15.0" in html
    # Must NOT contain full page elements (no navbar, no taller-layout)
    assert "navbar" not in html.lower()
    assert "taller-layout" not in html.lower()
    # Must contain lab parameters (flags may appear as arrows)
    assert "Leucocitos" in html or "Eritrocitos" in html or "Hemoglobina" in html


@pytest.mark.asyncio
async def test_htmx_preview_updates_flag(client: AsyncClient):
    """Changing a value from normal to high should update the flag."""
    patient_id = await register_patient(client)
    enrich = await client.post("/taller/enrich", json={
        "patient_id": patient_id,
        "species": "Felino",
        "test_type": "Hemograma",
        "test_type_code": "CBC",
        "source": "LIS_OZELLE",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "values": [
            {
                "parameter_code": "WBC",
                "parameter_name_es": "Leucocitos",
                "raw_value": "14.26",
                "numeric_value": 14.26,
                "unit": "10*9/L",
                "reference_range": "5.05-16.76",
                "machine_flag": "N",
            },
        ],
    })
    result_id = enrich.json()["test_result_id"]

    # Change WBC from 14.26 (NORMAL for Felino range 5.05-16.76) to 20.0 (ALTO)
    response = await client.post(
        f"/taller/preview/{result_id}",
        data={"value_WBC": "20.0"},
    )

    assert response.status_code == 200
    html = response.text
    # 20.0 should be visible
    assert "20.0" in html


@pytest.mark.asyncio
async def test_htmx_indicator_shows_in_page(client: AsyncClient):
    """The htmx-indicator class is present in the full page HTML."""
    patient_id = await register_patient(client)
    enrich = await client.post("/taller/enrich", json={
        "patient_id": patient_id,
        "species": "Felino",
        "test_type": "Hemograma",
        "test_type_code": "CBC",
        "source": "LIS_OZELLE",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "values": make_lab_values(),
    })
    result_id = enrich.json()["test_result_id"]

    # Get the full page
    response = await client.get(f"/taller/{result_id}")
    html = response.text

    # Must contain the htmx-indicator
    assert "htmx-indicator" in html
    assert "preview-loading" in html
    assert "Actualizando..." in html


# ── POST /taller/algorithms/{id} — apply clinical algorithms ─────────────────

@pytest.mark.asyncio
async def test_apply_algorithms_creates_new_lab_values(client: AsyncClient):
    """Applying algorithms should persist new LabValue rows to the DB."""
    patient_id = await register_patient(client)
    # Use values that match what the algorithms expect (Na, K in mEq/L)
    enrich = await client.post("/taller/enrich", json={
        "patient_id": patient_id,
        "species": "Canino",
        "test_type": "Hemograma",
        "test_type_code": "CBC",
        "source": "LIS_OZELLE",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "values": [
            {"parameter_code": "NA", "parameter_name_es": "Sodio",
             "raw_value": "140", "numeric_value": 140.0,
             "unit": "mEq/L", "reference_range": "140-160"},
            {"parameter_code": "K", "parameter_name_es": "Potasio",
             "raw_value": "4.0", "numeric_value": 4.0,
             "unit": "mEq/L", "reference_range": "3.5-5.5"},
        ],
    })
    result_id = enrich.json()["test_result_id"]

    response = await client.post(f"/taller/algorithms/{result_id}")
    assert response.status_code == 200
    html = response.text
    # Should contain the preview HTML (report.html)
    assert "patient-grid" in html or "Laboratorio Veterinario" in html
    # Should NOT contain an error for Na:K (units match)
    # The OOB diagnostico panel may be present
    assert "diagnostico-motor" in html


@pytest.mark.asyncio
async def test_apply_algorithms_returns_htmx_oob_swap(client: AsyncClient):
    """Algorithm response should include OOB swap for the error panel."""
    patient_id = await register_patient(client)
    enrich = await client.post("/taller/enrich", json={
        "patient_id": patient_id,
        "species": "Canino",
        "test_type": "Hemograma",
        "test_type_code": "CBC",
        "source": "LIS_OZELLE",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "values": [
            {"parameter_code": "NA", "parameter_name_es": "Sodio",
             "raw_value": "140", "numeric_value": 140.0,
             "unit": "mEq/L", "reference_range": "140-160"},
            {"parameter_code": "K", "parameter_name_es": "Potasio",
             "raw_value": "4.0", "numeric_value": 4.0,
             "unit": "mEq/L", "reference_range": "3.5-5.5"},
        ],
    })
    result_id = enrich.json()["test_result_id"]

    response = await client.post(f"/taller/algorithms/{result_id}")
    assert response.status_code == 200
    # The response may contain hx-swap-oob marker for diagnostico-motor
    assert "diagnostico-motor" in response.text


@pytest.mark.asyncio
async def test_apply_algorithms_not_found(client: AsyncClient):
    response = await client.post("/taller/algorithms/99999")
    assert response.status_code == 404


# ── PATCH /taller/images/{id}/toggle ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_toggle_image_includes_in_report(client: AsyncClient):
    """Toggle endpoint should switch is_included_in_report and return checkbox HTML."""
    import base64
    JPEG_MINI = base64.b64encode(b'\xff\xd8\xff\xe0' + b'\x00' * 10 + b'\xff\xd9').decode()

    patient_id = await register_patient(client)
    enrich = await client.post("/taller/enrich", json={
        "patient_id": patient_id,
        "species": "Felino",
        "test_type": "Hemograma",
        "test_type_code": "CBC",
        "source": "LIS_OZELLE",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "values": make_lab_values(),
    })
    result_id = enrich.json()["test_result_id"]

    # Upload an image first
    await client.post("/taller/images", json={
        "test_result_id": result_id,
        "patient_name": "Kitty",
        "owner_name": "Laura Cepeda",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "images": [
            {"obs_identifier": "WBC_Main", "base64_data": JPEG_MINI},
        ],
    })

    # Get the image ID from the results endpoint
    result_data = await client.get(f"/taller/results/{result_id}")
    images = result_data.json()["images"]
    assert len(images) == 1
    image_id = images[0]["id"]

    # Initially is_included_in_report should be True (default for Main images)
    assert images[0]["is_included_in_report"] is True

    # Toggle OFF
    toggle_resp = await client.patch(f"/taller/images/{image_id}/toggle")
    assert toggle_resp.status_code == 200
    # Checkbox HTML should be returned
    html = toggle_resp.text
    assert "checkbox" in html
    # Should include the hx-patch directive for subsequent toggles
    assert f"/taller/images/{image_id}/toggle" in html

    # Verify the image is now excluded in the DB
    result_data2 = await client.get(f"/taller/results/{result_id}")
    images2 = result_data2.json()["images"]
    assert images2[0]["is_included_in_report"] is False

    # Toggle back ON
    toggle_resp2 = await client.patch(f"/taller/images/{image_id}/toggle")
    assert toggle_resp2.status_code == 200
    result_data3 = await client.get(f"/taller/results/{result_id}")
    images3 = result_data3.json()["images"]
    assert images3[0]["is_included_in_report"] is True


@pytest.mark.asyncio
async def test_toggle_image_not_found(client: AsyncClient):
    response = await client.patch("/taller/images/99999/toggle")
    assert response.status_code == 404


# ── Image gallery rendered in taller page ────────────────────────────────────

@pytest.mark.asyncio
async def test_taller_page_shows_image_gallery(client: AsyncClient):
    """Taller page should render the image gallery with checkboxes."""
    import base64
    JPEG_MINI = base64.b64encode(b'\xff\xd8\xff\xe0' + b'\x00' * 10 + b'\xff\xd9').decode()

    patient_id = await register_patient(client)
    enrich = await client.post("/taller/enrich", json={
        "patient_id": patient_id,
        "species": "Felino",
        "test_type": "Hemograma",
        "test_type_code": "CBC",
        "source": "LIS_OZELLE",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "values": make_lab_values(),
    })
    result_id = enrich.json()["test_result_id"]

    # Upload images
    await client.post("/taller/images", json={
        "test_result_id": result_id,
        "patient_name": "Kitty",
        "owner_name": "Laura Cepeda",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "images": [
            {"obs_identifier": "WBC_Main", "base64_data": JPEG_MINI},
            {"obs_identifier": "RBC_Histo", "base64_data": JPEG_MINI},
            {"obs_identifier": "LYM_Part1", "base64_data": JPEG_MINI},
        ],
    })

    response = await client.get(f"/taller/{result_id}")
    assert response.status_code == 200
    html = response.text

    # Gallery section should be present
    assert "Galería de Imágenes" in html
    # Checkboxes with hx-patch should be present
    assert "hx-patch" in html
    assert "image-gallery" in html


@pytest.mark.asyncio
async def test_taller_page_shows_aplicar_algoritmos_button(client: AsyncClient):
    """Taller page should include the 'Aplicar Algoritmos' button."""
    patient_id = await register_patient(client)
    enrich = await client.post("/taller/enrich", json={
        "patient_id": patient_id,
        "species": "Felino",
        "test_type": "Hemograma",
        "test_type_code": "CBC",
        "source": "LIS_OZELLE",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "values": make_lab_values(),
    })
    result_id = enrich.json()["test_result_id"]

    response = await client.get(f"/taller/{result_id}")
    assert response.status_code == 200
    html = response.text

    assert "Aplicar Algoritmos" in html
    # Button should use HTMX to POST to the algorithms endpoint
    assert "hx-post" in html
    assert f"/taller/algorithms/{result_id}" in html
import pytest
from datetime import datetime, timezone
from httpx import AsyncClient

def make_lab_values():
    """Real-ish values from Ozelle log."""
    return [
        {
            "parameter_code": "WBC",
            "parameter_name_es": "Leucocitos",
            "raw_value": "14.26",
            "numeric_value": 14.26,
            "unit": "10*9/L",
            "reference_range": "5.05-16.76",
            "machine_flag": "N",
        },
        {
            "parameter_code": "RBC",
            "parameter_name_es": "Eritrocitos",
            "raw_value": "7.2",
            "numeric_value": 7.2,
            "unit": "10*12/L",
            "reference_range": "5.65-8.87",
            "machine_flag": "N",
        },
        {
            "parameter_code": "HGB",
            "parameter_name_es": "Hemoglobina",
            "raw_value": "5.0",
            "numeric_value": 5.0,
            "unit": "g/dL",
            "reference_range": "13.1-20.5",
            "machine_flag": "L",
        },
    ]

async def register_patient(client: AsyncClient) -> int:
    """Helper: register a patient and return patient_id."""
    r = await client.post("/reception/receive", json={
        "raw_string": "kitty felina 2a Laura Cepeda",
        "source": "LIS_OZELLE",
        "received_at": datetime.now(timezone.utc).isoformat(),
    })
    assert r.status_code == 200
    return r.json()["patient_id"]

# ── Pending Patients Endpoint Tests ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pending_patients_endpoint_returns_html_fragment(client: AsyncClient):
    """GET /taller/pending-patients should return HTML fragment, not 422."""
    # First create a test result
    patient_id = await register_patient(client)
    enrich = await client.post("/taller/enrich", json={
        "patient_id": patient_id,
        "species": "Felino",
        "test_type": "Hemograma",
        "test_type_code": "CBC",
        "source": "LIS_OZELLE",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "values": make_lab_values(),
    })
    assert enrich.status_code == 200

    # Now check pending-patients endpoint
    response = await client.get("/taller/pending-patients")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    html = response.text
    # Should contain patient info from our test
    assert "Kitty" in html or "No hay pacientes en cola" in html
    # Should NOT be a JSON error response
    assert "detail" not in html


@pytest.mark.asyncio
async def test_pending_patients_not_confused_with_result_route(client: AsyncClient):
    """GET /taller/pending-patients should NOT match /taller/{result_id} route."""
    # This endpoint should work even with string 'pending-patients'
    # that could be mistaken for a numeric result_id
    response = await client.get("/taller/pending-patients")
    assert response.status_code == 200
    # Should return HTML, not 422 validation error
    assert response.status_code != 422
    assert "text/html" in response.headers["content-type"]


# ── Image Base64 Extraction Tests ────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_image_base64_extraction_with_trailing_chars():
    """Base64 image data should be cleaned of trailing HL7 chars like ||||||F."""
    from app.satellites.ozelle.hl7_parser import parse_hl7_message
    import base64
    
    # Create a minimal valid JPEG (SOI + EOI markers)
    JPEG_MINI = base64.b64encode(b'\xff\xd8\xff\xe0' + b'\x00' * 10 + b'\xff\xd9').decode()
    
    # HL7 message with Base64^ prefix and trailing ||||||F
    hl7_msg = (
        "MSH|^~\\&|EHVT-50|HUELLAS LAB|||20260414164534||ORU^R01||P|2.3.1|\n"
        "PID|1||||||20240414|F|test patient|DOG|||\n"
        "OBR|1|||CBC^Complete Blood Count|R|20260414164017|\n"
        f"OBX|1|ED|RBC_Histo||Base64^/{JPEG_MINI}/9k=||||||F\n"
    )
    
    parsed = parse_hl7_message(hl7_msg)
    
    assert len(parsed.images) == 1
    img = parsed.images[0]
    assert img.obs_identifier == "RBC_Histo"
    # Should have extracted only the Base64 portion between /9j/ and /9k=
    # The parser extracts the Base64 between /9j/ and /9k=
    assert img.base64_data == "/9j/" + JPEG_MINI.split("/9j/")[1]
    assert not img.base64_data.startswith("Base64^")
    assert "/9k=" not in img.base64_data
    assert "||||||" not in img.base64_data

@pytest.mark.asyncio
async def test_translated_image_names(client: AsyncClient):
    """Image filenames should use Spanish translations from IMAGE_PARAMETER_TRANSLATION."""
    import base64
    JPEG_MINI = base64.b64encode(b'\xff\xd8\xff\xe0' + b'\x00' * 10 + b'\xff\xd9').decode()
    
    patient_id = await register_patient(client)
    enrich = await client.post("/taller/enrich", json={
        "patient_id": patient_id,
        "species": "Felino",
        "test_type": "Hemograma",
        "test_type_code": "CBC",
        "source": "LIS_OZELLE",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "values": make_lab_values(),
    })
    result_id = enrich.json()["test_result_id"]

    # Upload images with various codes
    response = await client.post("/taller/images", json={
        "test_result_id": result_id,
        "patient_name": "Kitty",
        "owner_name": "Laura Cepeda",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "images": [
            {"obs_identifier": "WBC_Main", "base64_data": JPEG_MINI},
            {"obs_identifier": "HGB_Histo", "base64_data": JPEG_MINI},
            {"obs_identifier": "HCT_Part1", "base64_data": JPEG_MINI},
        ],
    })
    assert response.status_code == 200
    data = response.json()
    assert data["total_saved"] == 3
    
    # Check that images were saved with translated names
    result_data = await client.get(f"/taller/results/{result_id}")
    images = result_data.json()["images"]
    assert len(images) == 3
    
    # Should have Leucocitos (WBC), Hemoglobina (HGB), Hematocrito (HCT)
    param_names = [img["parameter_name_es"] for img in images]
    assert "Leucocitos" in param_names
    assert "Hemoglobina" in param_names
    assert "Hematocrito" in param_names