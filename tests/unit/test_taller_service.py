"""
Tests for app.domains.taller.service — TallerService helpers and PDF generation logic.
"""
import pytest
import pytest_asyncio
from datetime import datetime, timezone
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
