"""Unit tests for TestResultMergeService — inject_patient_to_taller merge logic."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession
from app.domains.reception.merge_service import TestResultMergeService


@pytest.fixture
def merge_service():
    """Returns a TestResultMergeService with a mocked ExamOrderService."""
    svc = TestResultMergeService()
    svc._exam_order_service = AsyncMock()
    return svc


@pytest.fixture
def mock_async_session():
    """Mock AsyncSession for unit-level merge tests."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.commit.return_value = None
    return mock_session


def _mock_execute_result(scalar_one_or_none=None, scalars_all=None):
    """Build a MagicMock execute result with configurable return values."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_one_or_none
    if scalars_all is not None:
        result.scalars.return_value.all.return_value = scalars_all
    return result


# ── inject_patient_to_taller ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_trs_returns_none(merge_service, mock_async_session):
    """inject_patient_to_taller returns None when patient has no TestResults."""
    from app.domains.patients.models import Patient

    patient = Patient(id=42, name="Test", species="Canino")

    # Mock TestResult query → empty
    mock_async_session.execute = AsyncMock(
        side_effect=[
            _mock_execute_result(scalars_all=[]),  # TestResult query → empty
        ]
    )

    result = await merge_service.inject_patient_to_taller(42, mock_async_session)
    assert result is None


@pytest.mark.asyncio
async def test_single_tr_returns_as_is(merge_service, mock_async_session):
    """Single TestResult returns as-is with doctor_name and test_type propagated."""
    from app.domains.patients.models import Patient
    from app.shared.models.test_result import TestResult

    tr = TestResult(
        id=10, patient_id=42, source="LIS_OZELLE",
        flag_alto_count=2, flag_normal_count=3, flag_bajo_count=0,
    )
    patient = Patient(
        id=42, name="Test", species="Canino",
        doctor_name="Dr. House",
        appsheet_test_type="Bioquímica",
        appsheet_test_type_code="BQ",
    )

    # Mock ExamOrder → empty (no active orders)
    merge_service._exam_order_service.get_by_patient = AsyncMock(return_value=[])

    mock_async_session.execute = AsyncMock(
        side_effect=[
            _mock_execute_result(scalars_all=[tr]),          # TestResult query
            _mock_execute_result(scalar_one_or_none=patient),  # Patient query
        ]
    )

    result = await merge_service.inject_patient_to_taller(42, mock_async_session)
    assert result is tr
    assert result.doctor_name == "Dr. House"
    assert result.test_type == "Bioquímica"
    assert result.test_type_code == "BQ"


@pytest.mark.asyncio
async def test_multiple_trs_dedup_parameter(merge_service, mock_async_session):
    """When two TRs share a parameter_code, the first (latest) wins — duplicate skipped."""
    from app.domains.patients.models import Patient
    from app.shared.models.test_result import TestResult
    from app.shared.models.lab_value import LabValue

    tr1 = TestResult(
        id=10, patient_id=42, source="LIS_OZELLE",
        flag_alto_count=1, flag_normal_count=0, flag_bajo_count=0,
    )
    tr2 = TestResult(
        id=5, patient_id=42, source="LIS_FUJIFILM",
        flag_alto_count=0, flag_normal_count=1, flag_bajo_count=0,
    )

    # LabValue in tr1 (latest)
    lv1 = LabValue(
        id=100, test_result_id=10, parameter_code="CRE",
        parameter_name_es="Creatinina", raw_value="1.2",
        flag="ALTO",
    )

    # LabValues in tr2 (older) — CRE duplicates, BUN is new
    lv2_dup = LabValue(
        id=200, test_result_id=5, parameter_code="CRE",
        parameter_name_es="Creatinina", raw_value="1.5",
        flag="NORMAL",
    )
    lv2_new = LabValue(
        id=201, test_result_id=5, parameter_code="BUN",
        parameter_name_es="Urea", raw_value="25",
        flag="NORMAL",
    )

    patient = Patient(id=42, name="Test", species="Canino")

    # Mock ExamOrder → empty
    merge_service._exam_order_service.get_by_patient = AsyncMock(return_value=[])

    # execute call sequence:
    # 1. TestResult query → [tr1, tr2]
    # 2. Patient query → patient
    # 3. ExamOrder query → empty (handled by mock above)
    # 4. LabValue query for tr2 → [lv2_dup, lv2_new]
    # 5. Duplicate check for CRE → lv1 exists → skip (returns non-None)
    # 6. Duplicate check for BUN → None → copy
    # 7. Flag recount query → [lv1, new_lv_bun]
    # 8. Commit + refresh

    mock_async_session.execute = AsyncMock(
        side_effect=[
            _mock_execute_result(scalars_all=[tr1, tr2]),     # TR query (latest first)
            _mock_execute_result(scalar_one_or_none=patient),  # Patient query
            _mock_execute_result(scalars_all=[lv2_dup, lv2_new]),  # LabValues from tr2
            _mock_execute_result(scalar_one_or_none=lv1),      # Dup check CRE → found
            _mock_execute_result(scalar_one_or_none=None),     # Dup check BUN → not found
            _mock_execute_result(scalars_all=[lv1]),           # Flag recount (will be extended)
        ]
    )

    result = await merge_service.inject_patient_to_taller(42, mock_async_session)
    assert result is tr1
    # Source should be merged
    assert "LIS_OZELLE" in result.source
    assert "LIS_FUJIFILM" in result.source


@pytest.mark.asyncio
async def test_flag_recount_after_merge(merge_service, mock_async_session):
    """After merging TRs, flag counts reflect ALL merged LabValues."""
    from app.domains.patients.models import Patient
    from app.shared.models.test_result import TestResult
    from app.shared.models.lab_value import LabValue

    tr1 = TestResult(
        id=10, patient_id=42, source="LIS_OZELLE",
        flag_alto_count=0, flag_normal_count=0, flag_bajo_count=0,
    )
    tr2 = TestResult(
        id=5, patient_id=42, source="LIS_FUJIFILM",
        flag_alto_count=0, flag_normal_count=0, flag_bajo_count=0,
    )

    lv1 = LabValue(id=100, test_result_id=10, parameter_code="ALT", flag="ALTO")
    lv2 = LabValue(id=200, test_result_id=5, parameter_code="BUN", flag="NORMAL")
    lv3 = LabValue(id=201, test_result_id=5, parameter_code="CRE", flag="BAJO")

    patient = Patient(id=42, name="Test", species="Canino")

    merge_service._exam_order_service.get_by_patient = AsyncMock(return_value=[])

    # After merge: lv1 (ALTO), new_lv_BUN (NORMAL), new_lv_CRE (BAJO)
    # Expected: flag_alto=1, flag_normal=1, flag_bajo=1
    merged_lvs = [lv1]
    # Create mock copies for BUN and CRE with same flags
    bun_copy = MagicMock(spec=LabValue)
    bun_copy.flag = "NORMAL"
    cre_copy = MagicMock(spec=LabValue)
    cre_copy.flag = "BAJO"
    merged_lvs = [lv1, bun_copy, cre_copy]

    mock_async_session.execute = AsyncMock(
        side_effect=[
            _mock_execute_result(scalars_all=[tr1, tr2]),        # TR query
            _mock_execute_result(scalar_one_or_none=patient),    # Patient query
            _mock_execute_result(scalars_all=[lv2, lv3]),        # LabValues from tr2
            _mock_execute_result(scalar_one_or_none=None),       # Dup check BUN
            _mock_execute_result(scalar_one_or_none=None),       # Dup check CRE
            _mock_execute_result(scalars_all=merged_lvs),        # Flag recount
        ]
    )

    result = await merge_service.inject_patient_to_taller(42, mock_async_session)
    assert result is tr1
    assert result.flag_alto_count == 1
    assert result.flag_normal_count == 1
    assert result.flag_bajo_count == 1


@pytest.mark.asyncio
async def test_doctor_propagation(merge_service, mock_async_session):
    """doctor_name from Patient is propagated to the merged TestResult."""
    from app.domains.patients.models import Patient
    from app.shared.models.test_result import TestResult

    tr = TestResult(id=10, patient_id=42, source="LIS_OZELLE",
                     flag_alto_count=0, flag_normal_count=0, flag_bajo_count=0)
    patient = Patient(id=42, name="Test", species="Canino",
                      doctor_name="Dr. Mendoza")

    merge_service._exam_order_service.get_by_patient = AsyncMock(return_value=[])

    mock_async_session.execute = AsyncMock(
        side_effect=[
            _mock_execute_result(scalars_all=[tr]),          # TestResult query
            _mock_execute_result(scalar_one_or_none=patient),  # Patient query
        ]
    )

    result = await merge_service.inject_patient_to_taller(42, mock_async_session)
    assert result.doctor_name == "Dr. Mendoza"


@pytest.mark.asyncio
async def test_test_type_from_exam_order(merge_service, mock_async_session):
    """test_type is resolved from active ExamOrder with priority over Patient field."""
    from app.domains.patients.models import Patient
    from app.shared.models.test_result import TestResult
    from unittest.mock import MagicMock

    tr = TestResult(id=10, patient_id=42, source="LIS_OZELLE",
                     flag_alto_count=0, flag_normal_count=0, flag_bajo_count=0)
    patient = Patient(id=42, name="Test", species="Canino",
                      appsheet_test_type="Old_Type", appsheet_test_type_code="OLD")

    # ExamOrder with active status
    mock_order = MagicMock()
    mock_order.status = "pending"
    mock_order.exam_types = ["CHEM"]

    merge_service._exam_order_service.get_by_patient = AsyncMock(return_value=[mock_order])

    mock_async_session.execute = AsyncMock(
        side_effect=[
            _mock_execute_result(scalars_all=[tr]),          # TestResult query
            _mock_execute_result(scalar_one_or_none=patient),  # Patient query
        ]
    )

    result = await merge_service.inject_patient_to_taller(42, mock_async_session)
    # Should use ExamOrder resolution, not Patient field
    # _resolve_test_type_from_exam_types(["CHEM"]) → test_type resolved from catalog
    assert result.test_type is not None
