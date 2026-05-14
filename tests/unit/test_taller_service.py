"""
Tests for app.domains.taller.service — TallerService helpers and PDF generation logic.
"""
import pytest
import pytest_asyncio
from datetime import datetime, timezone
from unittest.mock import patch
from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.domains.patients.models import Patient
from app.shared.models.test_result import TestResult
from app.shared.models.lab_value import LabValue
from app.shared.models.patient_image import PatientImage
from app.domains.taller.service import (
    TallerService,
    _clean_parameter_code,
)


# ───────────────────────────────────────────────────────────────
# _clean_parameter_code() tests
# ───────────────────────────────────────────────────────────────

def test_clean_parameter_code_main_suffix():
    assert _clean_parameter_code("WBC_Main") == "WBC"


def test_clean_parameter_code_part_suffix():
    assert _clean_parameter_code("LYM_Part3") == "LYM#"


def test_clean_parameter_code_histo_suffix():
    assert _clean_parameter_code("RBC_Histo") == "RBC"


def test_clean_parameter_code_distribution_suffix():
    assert _clean_parameter_code("PLT_Distribution") == "PLT"


def test_clean_parameter_code_no_suffix():
    assert _clean_parameter_code("WBC") == "WBC"


def test_clean_parameter_code_keep_hash():
    """NSG# should keep the # — it's part of the canonical code."""
    assert _clean_parameter_code("NSG#") == "NSG#"


def test_clean_parameter_code_keep_percent():
    """NEU% should keep the % — it's part of the canonical code."""
    assert _clean_parameter_code("NEU%") == "NEU%"


def test_clean_parameter_code_alias_resolution():
    """RET should resolve to RET# via STANDARDS_MAPPING."""
    assert _clean_parameter_code("RET") == "RET#"


def test_clean_parameter_code_part_then_alias():
    """LYM_Part3 → LYM → LYM# via alias resolution."""
    assert _clean_parameter_code("LYM_Part3") == "LYM#"


# ───────────────────────────────────────────────────────────────
# get_test_result_full() dynamic resolution tests
# ───────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as s:
        yield s
    await engine.dispose()


def _make_patient() -> Patient:
    return Patient(
        name="Buddy",
        species="Canino",
        sex="Macho",
        owner_name="Juan Pérez",
        has_age=True,
        age_value=3,
        age_unit="años",
        age_display="3 años",
        source="LIS_OZELLE",
        normalized_name="buddy",
        normalized_owner="juan pérez",
    )


@pytest.mark.asyncio
async def test_get_test_result_full_dynamic_resolution(session):
    """PDF fields should come from clinical_standards.py, not stale DB columns."""
    patient = _make_patient()
    session.add(patient)
    await session.commit()
    await session.refresh(patient)

    tr = TestResult(
        patient_id=patient.id,
        test_type="Hemograma",
        test_type_code="CBC",
        source="LIS_OZELLE",
        status="completado",
        received_at=datetime.now(timezone.utc),
    )
    session.add(tr)
    await session.commit()
    await session.refresh(tr)

    # Insert LabValue with INTENTIONALLY WRONG/stale DB data
    lv = LabValue(
        test_result_id=tr.id,
        parameter_code="WBC_Main",          # machine suffix
        parameter_name_es="WRONG_NAME",     # stale name
        raw_value="14.26",
        numeric_value=14.26,
        unit="10*9/L",
        reference_range="0-999",            # stale range
        flag="ALTO",                        # stale flag
        machine_flag="N",
    )
    session.add(lv)
    await session.commit()
    await session.refresh(lv)

    service = TallerService()
    result = await service.get_test_result_full(tr.id, session)

    assert result is not None

    # Lab value should have dynamically-resolved fields
    lab = result["lab_values"][0]
    assert lab["parameter_code"] == "WBC_Main"          # original code preserved
    assert lab["parameter_name_es"] == "Leucocitos"      # from clinical_standards
    assert "5.05 - 16.76" in lab["reference_range"]      # from clinical_standards
    assert lab["flag"] == "NORMAL"                       # recomputed from standards
    assert lab["group"] == "Línea Blanca"

    # Summary should reflect recomputed flags, not DB counts
    assert result["summary"]["NORMAL"] == 1
    assert result["summary"]["ALTO"] == 0
    assert result["summary"]["BAJO"] == 0
    assert result["test_result"]["flag_normal_count"] == 1


@pytest.mark.asyncio
async def test_get_test_result_full_image_name_resolution(session):
    """Image parameter_name_es should be resolved from clinical_standards.py."""
    patient = _make_patient()
    session.add(patient)
    await session.commit()
    await session.refresh(patient)

    tr = TestResult(
        patient_id=patient.id,
        test_type="Hemograma",
        test_type_code="CBC",
        source="LIS_OZELLE",
        status="completado",
        received_at=datetime.now(timezone.utc),
    )
    session.add(tr)
    await session.commit()
    await session.refresh(tr)

    img = PatientImage(
        test_result_id=tr.id,
        parameter_code="RET",               # alias that resolves to RET#
        parameter_name_es="WRONG_IMG_NAME", # stale name
        file_path="images/Buddy/20260507/RET.png",
        patient_folder="images/Buddy/20260507/",
    )
    session.add(img)
    await session.commit()
    await session.refresh(img)

    service = TallerService()
    result = await service.get_test_result_full(tr.id, session)

    assert result is not None
    image = result["images"][0]
    assert image["obs_identifier"] == "RET"
    assert image["parameter_name_es"] == "Reticulocitos Absolutos"  # resolved from clinical_standards


@pytest.mark.asyncio
async def test_get_test_result_full_flag_recomputation(session):
    """Flag should be recomputed from clinical_standards ranges, not DB flag."""
    patient = _make_patient()
    session.add(patient)
    await session.commit()
    await session.refresh(patient)

    tr = TestResult(
        patient_id=patient.id,
        test_type="Hemograma",
        test_type_code="CBC",
        source="LIS_OZELLE",
        status="completado",
        received_at=datetime.now(timezone.utc),
    )
    session.add(tr)
    await session.commit()
    await session.refresh(tr)

    # RBC value that is ALTO for Canino (> 8.87)
    lv = LabValue(
        test_result_id=tr.id,
        parameter_code="RBC",
        parameter_name_es="Eritrocitos",
        raw_value="9.5",
        numeric_value=9.5,
        unit="10*12/L",
        reference_range="5.65-8.87",
        flag="NORMAL",  # stale — should be recomputed to ALTO
        machine_flag="N",
    )
    session.add(lv)
    await session.commit()
    await session.refresh(lv)

    service = TallerService()
    result = await service.get_test_result_full(tr.id, session)

    assert result is not None
    lab = result["lab_values"][0]
    assert lab["flag"] == "ALTO"
    assert result["summary"]["ALTO"] == 1
    assert result["summary"]["NORMAL"] == 0


@pytest.mark.asyncio
async def test_get_test_result_full_null_numeric_value(session):
    """Lab values with no numeric_value should default to NORMAL flag."""
    patient = _make_patient()
    session.add(patient)
    await session.commit()
    await session.refresh(patient)

    tr = TestResult(
        patient_id=patient.id,
        test_type="Hemograma",
        test_type_code="CBC",
        source="LIS_OZELLE",
        status="completado",
        received_at=datetime.now(timezone.utc),
    )
    session.add(tr)
    await session.commit()
    await session.refresh(tr)

    lv = LabValue(
        test_result_id=tr.id,
        parameter_code="WBC",
        parameter_name_es="Leucocitos",
        raw_value="N/A",
        numeric_value=None,
        unit="10*9/L",
        reference_range="5.05-16.76",
        flag="ALTO",
        machine_flag="N",
    )
    session.add(lv)
    await session.commit()
    await session.refresh(lv)

    service = TallerService()
    result = await service.get_test_result_full(tr.id, session)

    assert result is not None
    lab = result["lab_values"][0]
    assert lab["flag"] == "NORMAL"
    assert result["summary"]["NORMAL"] == 1


# ───────────────────────────────────────────────────────────────
# UREA virtual value injection tests (Task 2.5)
# ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_test_result_full_urea_injected_when_bun_present(session):
    """Scenario: BUN present with numeric value → UREA virtual value injected.

    UREA = BUN × 2.14, flagged using clinical_standards ranges.
    Virtual LabValue has id=None to signal 'no DB row'.
    """
    patient = _make_patient()
    session.add(patient)
    await session.commit()
    await session.refresh(patient)

    tr = TestResult(
        patient_id=patient.id,
        test_type="Química Sanguínea",
        test_type_code="CHEM",
        source="LIS_FUJIFILM",
        status="completado",
        received_at=datetime.now(timezone.utc),
    )
    session.add(tr)
    await session.commit()
    await session.refresh(tr)

    # Insert BUN = 20.0 mg/dL (NORMAL for Canino: 15-35)
    lv = LabValue(
        test_result_id=tr.id,
        parameter_code="BUN",
        parameter_name_es="Nitrógeno Ureico",
        raw_value="20.0",
        numeric_value=20.0,
        unit="mg/dL",
        reference_range="15-35",
        flag="NORMAL",
        machine_flag="N",
    )
    session.add(lv)
    await session.commit()

    # Patch VETERINARY_STANDARDS so UREA is known for flagging + name resolution
    urea_entry = {
        'UREA': {
            'name': 'Urea',
            'unit': 'mg/dL',
            'ranges': {
                'canine': {'min': 32.1, 'max': 74.9},
                'feline': {'min': 32.1, 'max': 74.9},
            },
            'short_name': 'Urea',
        },
    }
    from clinical_standards import VETERINARY_STANDARDS
    with patch.dict(VETERINARY_STANDARDS, urea_entry):
        service = TallerService()
        result = await service.get_test_result_full(tr.id, session)

    assert result is not None
    lab_values = result["lab_values"]

    # Find UREA in lab values
    urea_lv = next((lv for lv in lab_values if lv["parameter_code"] == "UREA"), None)
    assert urea_lv is not None, "UREA virtual value should be present"
    assert urea_lv["id"] is None, "Virtual UREA should have id=None"
    assert urea_lv["numeric_value"] == 42.8, f"Expected UREA=42.8 (BUN 20.0 × 2.14), got {urea_lv['numeric_value']}"
    assert urea_lv["unit"] == "mg/dL"
    assert "32.1" in urea_lv["reference_range"], f"Expected reference range 32.1-74.9, got {urea_lv['reference_range']}"
    assert urea_lv["group"] == "QUÍMICA SANGUÍNEA"
    assert urea_lv["flag"] == "NORMAL"

    # Summary should include UREA
    assert result["summary"]["NORMAL"] >= 1


@pytest.mark.asyncio
async def test_get_test_result_full_no_bun_no_urea(session):
    """Scenario: BUN not present → no UREA injected.

    If BUN is missing from lab values, UREA should not appear.
    """
    patient = _make_patient()
    session.add(patient)
    await session.commit()
    await session.refresh(patient)

    tr = TestResult(
        patient_id=patient.id,
        test_type="Química Sanguínea",
        test_type_code="CHEM",
        source="LIS_FUJIFILM",
        status="completado",
        received_at=datetime.now(timezone.utc),
    )
    session.add(tr)
    await session.commit()
    await session.refresh(tr)

    # Insert CRE but NOT BUN
    lv = LabValue(
        test_result_id=tr.id,
        parameter_code="CRE",
        parameter_name_es="Creatinina",
        raw_value="1.0",
        numeric_value=1.0,
        unit="mg/dL",
        reference_range="0.6-1.6",
        flag="NORMAL",
        machine_flag="N",
    )
    session.add(lv)
    await session.commit()

    service = TallerService()
    result = await service.get_test_result_full(tr.id, session)

    assert result is not None
    ureas = [lv for lv in result["lab_values"] if lv["parameter_code"] == "UREA"]
    assert len(ureas) == 0, "UREA should NOT be present when BUN is absent"


@pytest.mark.asyncio
async def test_get_test_result_full_bun_non_numeric_no_urea(session):
    """Scenario: BUN present but non-numeric → no UREA injected.

    If BUN has no numeric_value, we cannot compute UREA.
    """
    patient = _make_patient()
    session.add(patient)
    await session.commit()
    await session.refresh(patient)

    tr = TestResult(
        patient_id=patient.id,
        test_type="Química Sanguínea",
        test_type_code="CHEM",
        source="LIS_FUJIFILM",
        status="completado",
        received_at=datetime.now(timezone.utc),
    )
    session.add(tr)
    await session.commit()
    await session.refresh(tr)

    # BUN with non-numeric value
    lv = LabValue(
        test_result_id=tr.id,
        parameter_code="BUN",
        parameter_name_es="Nitrógeno Ureico",
        raw_value="N/A",
        numeric_value=None,
        unit="mg/dL",
        reference_range="15-35",
        flag="NORMAL",
        machine_flag="N",
    )
    session.add(lv)
    await session.commit()

    service = TallerService()
    result = await service.get_test_result_full(tr.id, session)

    assert result is not None
    ureas = [lv for lv in result["lab_values"] if lv["parameter_code"] == "UREA"]
    assert len(ureas) == 0, "UREA should NOT be present when BUN is non-numeric"


@pytest.mark.asyncio
async def test_get_test_result_full_urea_flagged_high(session):
    """Scenario: BUN high → UREA flagged ALTO.

    BUN=80 (above 35 for Canino) → UREA=171.2 (> 74.9) → ALTO.
    """
    patient = _make_patient()
    session.add(patient)
    await session.commit()
    await session.refresh(patient)

    tr = TestResult(
        patient_id=patient.id,
        test_type="Química Sanguínea",
        test_type_code="CHEM",
        source="LIS_FUJIFILM",
        status="completado",
        received_at=datetime.now(timezone.utc),
    )
    session.add(tr)
    await session.commit()
    await session.refresh(tr)

    lv = LabValue(
        test_result_id=tr.id,
        parameter_code="BUN",
        parameter_name_es="Nitrógeno Ureico",
        raw_value="80.0",
        numeric_value=80.0,
        unit="mg/dL",
        reference_range="15-35",
        flag="ALTO",
        machine_flag="N",
    )
    session.add(lv)
    await session.commit()

    # Patch VETERINARY_STANDARDS so UREA is known for flagging
    urea_entry = {
        'UREA': {
            'name': 'Urea',
            'unit': 'mg/dL',
            'ranges': {
                'canine': {'min': 32.1, 'max': 74.9},
                'feline': {'min': 32.1, 'max': 74.9},
            },
            'short_name': 'Urea',
        },
    }
    from clinical_standards import VETERINARY_STANDARDS
    with patch.dict(VETERINARY_STANDARDS, urea_entry):
        service = TallerService()
        result = await service.get_test_result_full(tr.id, session)

    assert result is not None
    urea_lv = next((lv for lv in result["lab_values"] if lv["parameter_code"] == "UREA"), None)
    assert urea_lv is not None
    assert urea_lv["numeric_value"] == 171.2  # 80 × 2.14
    assert urea_lv["flag"] == "ALTO"


@pytest.mark.asyncio
async def test_get_test_result_full_interpretations(session):
    """Scenario: get_test_result_full() returns clinical interpretations.

    When LabValues trigger algorithm-derived results (e.g., BUN/CRE ratio),
    the interpretations list should be populated with clinical notes.
    """
    patient = _make_patient()
    session.add(patient)
    await session.commit()
    await session.refresh(patient)

    tr = TestResult(
        patient_id=patient.id,
        test_type="Química Sanguínea",
        test_type_code="CHEM",
        source="LIS_FUJIFILM",
        status="completado",
        received_at=datetime.now(timezone.utc),
    )
    session.add(tr)
    await session.commit()
    await session.refresh(tr)

    # CRE + BUN values that trigger the BUN/CRE ratio algorithm
    lv_cre = LabValue(
        test_result_id=tr.id,
        parameter_code="CRE",
        parameter_name_es="Creatinina",
        raw_value="1.0",
        numeric_value=1.0,
        unit="mg/dL",
        reference_range="0.5-1.5",
        flag="NORMAL",
        machine_flag="N",
    )
    lv_bun = LabValue(
        test_result_id=tr.id,
        parameter_code="BUN",
        parameter_name_es="BUN",
        raw_value="15.0",
        numeric_value=15.0,
        unit="mg/dL",
        reference_range="7-27",
        flag="NORMAL",
        machine_flag="N",
    )
    session.add(lv_cre)
    session.add(lv_bun)
    await session.commit()

    service = TallerService()
    result = await service.get_test_result_full(tr.id, session)

    assert result is not None
    assert "interpretations" in result
    # BUN(15) / CRE(1) = 15 which is ≤ 30 → RATIO_BUN_CRE_NORMAL interpretation
    assert len(result["interpretations"]) > 0
    interp = result["interpretations"][0]
    assert "parameter_code" in interp
    assert "text_es" in interp
    assert "severity" in interp
