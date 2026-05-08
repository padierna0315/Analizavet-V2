"""
Full Pipeline Integration Test — Phase 16

Tests the complete Ozelle → Reception → Taller → DB pipeline.
"""

import pytest
import pytest_asyncio
import os
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.domains.patients.models import Patient
from app.shared.models.test_result import TestResult
from app.shared.models.lab_value import LabValue
from app.shared.models.patient_image import PatientImage
from app.tasks.hl7_processor import _async_process_pipeline
from app.satellites.ozelle.hl7_parser import parse_hl7_message
from app.domains.reception.schemas import PatientSource
from tests.conftest import _get_engine


# A real 1x1 white JPEG image encoded in base64 (divisible by 4)
_REAL_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a"
    "HBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAHwAAAQUBAQEB"
    "AQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMQYE1F"
    "hByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1"
    "hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLD"
    "xMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/9oACAEBAAA/APvV/9k="
)

REAL_HL7_MSG = (
    "MSH|^~\\&|EHVT-50|HUELLAS LAB|||20260414164534||ORU^R01|MSG001|P|2.3.1\r\n"
    "PID|1||||||20240414|F|kitty felina 2a Laura Cepeda|DOG|||\r\n"
    "OBR|1|||CBC^Complete Blood Count|R|20260414164017|20260414164017|20260414164017|||||||\r\n"
    "OBX|1|ST|WBC^||11.02|10*9/L|5.05 - 16.76|N|||F\r\n"
    "OBX|2|ST|NEU#^||4.96|10*9/L|2.95 - 11.64|N|||F\r\n"
    f"OBX|3|ED|WBC_Main^||{_REAL_JPEG_B64}|||||F\r\n"
)


@pytest.mark.asyncio
async def test_full_pipeline_execution(tmp_path, monkeypatch):
    """
    Test the full Ozelle -> Reception -> Taller -> DB pipeline.

    Inject a real HL7 message into the Dramatiq actor, then verify:
    - One Patient was created/updated (normalized from raw string)
    - One TestResult was created
    - Lab values were flagged and stored
    - Images were saved to disk

    Note: This test runs AFTER other integration tests in the same session,
    so the shared in-memory DB may already contain patients from prior tests.
    We verify pipeline behavior (creating/updating patient, creating result,
    flagging values, saving images) rather than exact row counts.
    """
    # ── Patch AsyncSessionLocal in hl7_processor module so it writes to test DB ──
    from sqlalchemy.orm import sessionmaker
    engine = _get_engine()
    test_session_maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.tasks.hl7_processor.AsyncSessionLocal", test_session_maker)

    # ── Patch ImageHandlingService so we don't pollute the real disk ─────────────
    from app.domains.taller.images import ImageHandlingService
    original_init = ImageHandlingService.__init__

    def _patched_init(self):
        original_init(self)
        self._base_dir = str(tmp_path)

    monkeypatch.setattr(ImageHandlingService, "__init__", _patched_init)

    # ── Count patients before pipeline runs ───────────────────────────────────
    async with test_session_maker() as session:
        patients_res = await session.execute(select(Patient))
        patients_before = len(patients_res.scalars().all())

    # ── Parse the HL7 message and call the pipeline directly ────────────────────
    parsed = parse_hl7_message(REAL_HL7_MSG)
    await _async_process_pipeline(parsed, PatientSource.LIS_OZELLE.value)

    # ── Verify DB State ──────────────────────────────────────────────────────────
    async with test_session_maker() as session:
        # Patient (Kitty) was either created or found via deduplication
        patients_res = await session.execute(select(Patient).where(Patient.name == "Kitty"))
        patients = patients_res.scalars().all()
        assert len(patients) >= 1, f"Expected at least 1 patient named Kitty, got {len(patients)}"
        p = patients[0]
        assert p.species == "Felino", f"Expected 'Felino', got '{p.species}'"
        assert p.sex == "Hembra", f"Expected 'Hembra', got '{p.sex}'"
        assert p.owner_name == "Laura Cepeda", f"Got '{p.owner_name}'"

        # TestResult
        tr_res = await session.execute(select(TestResult).where(TestResult.patient_id == p.id))
        test_results = tr_res.scalars().all()
        assert len(test_results) == 1, f"Expected 1 test result, got {len(test_results)}"
        tr = test_results[0]
        assert tr.test_type_code == "CBC", f"Expected 'CBC', got '{tr.test_type_code}'"
        assert tr.status == "listo", f"Expected 'listo', got '{tr.status}'"

        # LabValues
        lv_res = await session.execute(select(LabValue).where(LabValue.test_result_id == tr.id))
        lab_values = lv_res.scalars().all()
        assert len(lab_values) == 2, f"Expected 2 lab values, got {len(lab_values)}"
        codes = {lv.parameter_code for lv in lab_values}
        assert "WBC" in codes, f"WBC missing from {codes}"
        assert "NEU#" in codes, f"NEU# missing from {codes}"

        # Images
        img_res = await session.execute(
            select(PatientImage).where(PatientImage.test_result_id == tr.id)
        )
        images = img_res.scalars().all()
        assert len(images) == 1, f"Expected 1 image, got {len(images)}"
        img = images[0]
        assert img.parameter_code == "WBC_Main", f"Expected 'WBC_Main', got '{img.parameter_code}'"
        assert img.parameter_name_es == "Leucocitos", f"Expected 'Leucocitos', got '{img.parameter_name_es}'"
        assert "Leucocitos_Main.jpg" in img.file_path, f"Got '{img.file_path}'"

        # Verify file actually exists on disk
        assert os.path.exists(img.file_path), f"Image file not found: {img.file_path}"
