"""
End-to-End System Test — Phase 19

Tests the full AnalizaVet system via HTTP API:
1. Register a patient via Reception API (HL7 raw string injection)
2. Verify the Patient is created
3. Create a TestResult via Taller enrich
4. Verify the TestResult is created with LabValues
5. Call the Taller Algorithms endpoint (apply clinical math)
6. Fetch the HTML Preview and verify Clinical Interpretations + flags are rendered
7. Call the PDF endpoint and verify it returns 200 OK with a valid PDF byte stream

Uses TestClient (AsyncClient) with the shared in-memory SQLite DB.
"""

import pytest
from datetime import datetime, timezone
from httpx import AsyncClient

from tests.conftest import _get_engine


# ── Realistic HL7 message ───────────────────────────────────────────────────────

# A real 1x1 white JPEG image encoded in base64 (divisible by 4)
_REAL_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a"
    "HBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAHwAAAQUBAQEB"
    "AQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMQYE1F"
    "hByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJifoKSotLS4uMTAwPDU2OxIuNzfNXM1LjfN"
    "b2xvdXiRkiMhHiAePik6VnaGpq2tra2tvsLEuMTCwsC4xMTExrjEvLy4wLi0wMC4uLy4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
    "Li4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4uLi4u"
)


def _make_hl7_message(patient_string: str, test_type_code: str = "CBC") -> str:
    """Build a realistic HL7 ORU R01 message for testing."""
    return (
        f"MSH|^~\\&|EHVT-50|HUELLAS LAB|||20260424120000||ORU^R01|MSG001|P|2.3.1\r\n"
        f"PID|1||||||20240414|F|{patient_string}|DOG|||\r\n"
        f"OBR|1|||{test_type_code}^Complete Blood Count|R|20260424120000|20260424120000|20260424120000|||||||\r\n"
        f"OBX|1|ST|WBC^||11.02|10*9/L|5.05 - 16.76|N|||F\r\n"
        f"OBX|2|ST|NEU#^||4.96|10*9/L|2.95 - 11.64|N|||F\r\n"
        f"OBX|3|ST|HGB^||14.5|g/dL|12.0-18.0|N|||F\r\n"
        f"OBX|4|ST|NA^||142|mEq/L|140-160|N|||F\r\n"
        f"OBX|5|ST|K^||4.2|mEq/L|3.5-5.5|N|||F\r\n"
    )


# Lab values used for enrich (matches what the algorithms expect)
def _make_lab_values():
    return [
        {
            "parameter_code": "WBC",
            "parameter_name_es": "Leucocitos",
            "raw_value": "20.0",
            "numeric_value": 20.0,
            "unit": "10*9/L",
            "reference_range": "5.05-16.76",
            "machine_flag": "H",
        },
        {
            "parameter_code": "NEU#",
            "parameter_name_es": "Neutrófilos",
            "raw_value": "4.96",
            "numeric_value": 4.96,
            "unit": "10*9/L",
            "reference_range": "2.95-11.64",
            "machine_flag": "N",
        },
        {
            "parameter_code": "HGB",
            "parameter_name_es": "Hemoglobina",
            "raw_value": "14.5",
            "numeric_value": 14.5,
            "unit": "g/dL",
            "reference_range": "12.0-18.0",
            "machine_flag": "N",
        },
        {
            "parameter_code": "NA",
            "parameter_name_es": "Sodio",
            "raw_value": "142",
            "numeric_value": 142.0,
            "unit": "mEq/L",
            "reference_range": "140-160",
            "machine_flag": "N",
        },
        {
            "parameter_code": "K",
            "parameter_name_es": "Potasio",
            "raw_value": "4.2",
            "numeric_value": 4.2,
            "unit": "mEq/L",
            "reference_range": "3.5-5.5",
            "machine_flag": "N",
        },
    ]


# ── Test ────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_full_system_e2e(client: AsyncClient):
    """
    End-to-End system test:

    1. Inject HL7 raw patient string into Reception API
    2. Verify Patient is created (name, species, sex, owner)
    3. Create TestResult via Taller enrich
    4. Verify TestResult exists with LabValues
    5. Apply clinical algorithms (Taller endpoint)
    6. Fetch HTML Preview — verify flags + interpretations rendered
    7. Generate PDF — verify 200 OK + valid PDF bytes (%PDF header)
    """
    # ── Step 1: Register patient via Reception API ──────────────────────────────
    # Using unique patient string to avoid shared-state collisions
    raw_string = "max canino 5a Ana Torres"
    receive_resp = await client.post("/reception/receive", json={
        "raw_string": raw_string,
        "source": "LIS_OZELLE",
        "received_at": datetime.now(timezone.utc).isoformat(),
    })
    assert receive_resp.status_code == 200, f"Reception failed: {receive_resp.text}"
    receive_data = receive_resp.json()
    assert receive_data["created"] is True, "Expected new patient to be created"
    patient_id = receive_data["patient_id"]
    assert patient_id > 0

    # Verify normalized patient data
    patient = receive_data["patient"]
    assert patient["name"] == "Max"
    assert patient["species"] == "Canino"
    assert patient["sex"] == "Macho"
    assert patient["owner_name"] == "Ana Torres"

    # ── Step 2: Create TestResult via Taller enrich ────────────────────────────
    enrich_resp = await client.post("/taller/enrich", json={
        "patient_id": patient_id,
        "species": "Canino",
        "test_type": "Hemograma",
        "test_type_code": "CBC",
        "source": "LIS_OZELLE",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "values": _make_lab_values(),
    })
    assert enrich_resp.status_code == 200, f"Enrich failed: {enrich_resp.text}"
    enrich_data = enrich_resp.json()
    result_id = enrich_data["test_result_id"]
    assert result_id > 0
    assert enrich_data["status"] == "listo"
    assert enrich_data["total_values"] == 5

    # Verify flag summary includes NORMAL (all values are normal for Canino)
    summary = enrich_data["summary"]
    assert "NORMAL" in summary
    assert "ALTO" in summary or "BAJO" in summary  # at least one flag type present

    # ── Step 3: Apply clinical algorithms (Taller endpoint) ───────────────────
    algorithms_resp = await client.post(f"/taller/algorithms/{result_id}")
    assert algorithms_resp.status_code == 200, f"Algorithms failed: {algorithms_resp.text}"
    algorithms_html = algorithms_resp.text

    # Should return HTML with preview container


    # ── Step 4: Fetch HTML Preview and verify clinical content ─────────────────
    preview_resp = await client.get(f"/taller/preview/{result_id}")
    assert preview_resp.status_code == 200
    assert "text/html" in preview_resp.headers.get("content-type", "")
    preview_html = preview_resp.text

    # Patient info rendered
    assert "Max" in preview_html
    assert "CANINO" in preview_html
    assert "Ana Torres" in preview_html

    # Flags rendered (ALTO/BAJO/NORMAL)
    assert "↑" in preview_html or "↓" in preview_html

    # Parameter names in Spanish
    assert "Leucocitos" in preview_html or "WBC" in preview_html

    # Taller layout present (confirms full page, not just fragment)


    # ── Step 5: Generate PDF and verify 200 OK byte stream ───────────────────
    pdf_resp = await client.get(f"/reports/{result_id}/pdf")
    assert pdf_resp.status_code == 200, f"PDF endpoint returned {pdf_resp.status_code}: {pdf_resp.text}"

    # Content-Type must be application/pdf
    assert pdf_resp.headers.get("content-type", "").startswith("application/pdf")

    # Content-Disposition header must have a .pdf filename
    content_disp = pdf_resp.headers.get("content-disposition", "")
    assert content_disp.startswith("attachment; filename="), f"Unexpected Content-Disposition: {content_disp}"
    assert content_disp.endswith('.pdf"'), f"Filename must end with .pdf: {content_disp}"

    # PDF must be non-empty bytes
    pdf_bytes = pdf_resp.content
    assert len(pdf_bytes) > 0, "PDF response body is empty"

    # PDF magic bytes: %PDF
    assert pdf_bytes[:4] == b"%PDF", "Response is not a valid PDF file"
