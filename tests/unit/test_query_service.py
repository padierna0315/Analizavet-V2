"""Unit tests for WaitingRoomQueryService — waiting room queries and single patient card."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession
from app.domains.reception.query_service import WaitingRoomQueryService


@pytest.fixture
def query_service():
    """Returns a WaitingRoomQueryService with a mocked ExamOrderService."""
    svc = WaitingRoomQueryService()
    svc._exam_order_service = AsyncMock()
    return svc


@pytest.fixture
def mock_async_session():
    """Mock AsyncSession for unit-level query tests."""
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


# ── get_waiting_room_patients ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_waiting_room_patients_returns_formatted_list(
    query_service, mock_async_session
):
    """get_waiting_room_patients returns formatted patient dicts with exam_orders and result_id."""
    from app.domains.patients.models import Patient
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    p1 = Patient(
        id=1, name="Alpha", species="Canino", sex="Macho",
        owner_name="OwnerA", source="MANUAL",
        normalized_name="alpha", normalized_owner="ownera",
        waiting_room_status="active", session_code="A1",
        created_at=now, updated_at=now,
        age_display="3 años", appsheet_test_type="Bioquímica",
        appsheet_test_type_code="BQ",
    )
    p2 = Patient(
        id=2, name="Beta", species="Felino", sex="Hembra",
        owner_name="OwnerB", source="LIS_OZELLE",
        normalized_name="beta", normalized_owner="ownerb",
        waiting_room_status="active", session_code="B1",
        created_at=now, updated_at=now,
        age_display="2 años",
    )

    # Mock the main Patient query
    main_result = MagicMock()
    main_result.scalars.return_value.all.return_value = [p1, p2]

    # Mock the TestResult sub-queries (one per patient)
    tr_result_1 = _mock_execute_result(scalar_one_or_none=10)
    tr_result_2 = _mock_execute_result(scalar_one_or_none=20)

    mock_async_session.execute = AsyncMock(
        side_effect=[main_result, tr_result_1, tr_result_2]
    )

    # Mock ExamOrderService.get_by_patient
    mock_order_1 = MagicMock()
    mock_order_1.id = 100
    mock_order_1.session_code = "A1"
    mock_order_1.exam_types = "Bioquímica"
    mock_order_1.status = "pending"

    mock_order_2 = MagicMock()
    mock_order_2.id = 200
    mock_order_2.session_code = "B1"
    mock_order_2.exam_types = "Hemograma"
    mock_order_2.status = "partial"

    query_service._exam_order_service.get_by_patient = AsyncMock(
        side_effect=[
            [mock_order_1],  # for p1
            [mock_order_2],  # for p2
        ]
    )

    result = await query_service.get_waiting_room_patients(mock_async_session)

    assert len(result) == 2

    # Patient 1
    assert result[0]["id"] == 1
    assert result[0]["name"] == "Alpha"
    assert result[0]["result_id"] == 10
    assert result[0]["waiting_room_status"] == "active"
    assert len(result[0]["exam_orders"]) == 1
    assert result[0]["exam_orders"][0]["id"] == 100

    # Patient 2
    assert result[1]["id"] == 2
    assert result[1]["name"] == "Beta"
    assert result[1]["result_id"] == 20
    assert len(result[1]["exam_orders"]) == 1
    assert result[1]["exam_orders"][0]["id"] == 200


@pytest.mark.asyncio
async def test_get_waiting_room_patients_returns_empty_when_no_active(
    query_service, mock_async_session
):
    """get_waiting_room_patients returns [] when no active patients exist."""
    main_result = MagicMock()
    main_result.scalars.return_value.all.return_value = []

    mock_async_session.execute = AsyncMock(return_value=main_result)

    result = await query_service.get_waiting_room_patients(mock_async_session)

    assert result == []
    mock_async_session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_get_waiting_room_patients_handles_patient_without_exam_orders(
    query_service, mock_async_session
):
    """get_waiting_room_patients returns empty exam_orders when patient has none."""
    from app.domains.patients.models import Patient
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    p1 = Patient(
        id=1, name="Alpha", species="Canino", sex="Macho",
        owner_name="OwnerA", source="MANUAL",
        normalized_name="alpha", normalized_owner="ownera",
        waiting_room_status="active", session_code=None,
        created_at=now, updated_at=now,
    )

    main_result = MagicMock()
    main_result.scalars.return_value.all.return_value = [p1]

    tr_result = _mock_execute_result(scalar_one_or_none=None)

    mock_async_session.execute = AsyncMock(
        side_effect=[main_result, tr_result]
    )

    query_service._exam_order_service.get_by_patient = AsyncMock(return_value=[])

    result = await query_service.get_waiting_room_patients(mock_async_session)

    assert len(result) == 1
    assert result[0]["id"] == 1
    assert result[0]["exam_orders"] == []
    assert result[0]["result_id"] is None


# ── get_single_patient_for_card ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_single_patient_for_card_returns_complete_dict(
    query_service, mock_async_session
):
    """get_single_patient_for_card returns a fully formatted dict for an existing patient."""
    from app.domains.patients.models import Patient
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    p = Patient(
        id=42, name="Gamma", species="Canino", sex="Macho",
        owner_name="OwnerC", source="MANUAL",
        normalized_name="gamma", normalized_owner="ownerc",
        waiting_room_status="active", session_code="C1",
        created_at=now, updated_at=now,
        age_display="5 años",
        appsheet_test_type="Perfil Renal",
        appsheet_test_type_code="PR",
    )
    mock_async_session.get = AsyncMock(return_value=p)

    tr_result = _mock_execute_result(scalar_one_or_none=55)
    mock_async_session.execute = AsyncMock(return_value=tr_result)

    mock_order = MagicMock()
    mock_order.id = 300
    mock_order.session_code = "C1"
    mock_order.exam_types = "Perfil Renal"
    mock_order.status = "pending"
    query_service._exam_order_service.get_by_patient = AsyncMock(return_value=[mock_order])

    result = await query_service.get_single_patient_for_card(42, mock_async_session)

    assert result is not None
    assert result["id"] == 42
    assert result["name"] == "Gamma"
    assert result["species"] == "Canino"
    assert result["result_id"] == 55
    assert result["waiting_room_status"] == "active"
    assert result["session_code"] == "C1"
    assert len(result["exam_orders"]) == 1
    assert result["exam_orders"][0]["id"] == 300
    assert result["appsheet_test_type"] == "Perfil Renal"
    assert result["appsheet_test_type_code"] == "PR"
    # Verify ISO format for timestamps
    assert "T" in result["created_at"]
    assert "T" in result["updated_at"]


@pytest.mark.asyncio
async def test_get_single_patient_for_card_returns_none_for_missing_patient(
    query_service, mock_async_session
):
    """get_single_patient_for_card returns None when patient does not exist."""
    mock_async_session.get = AsyncMock(return_value=None)

    result = await query_service.get_single_patient_for_card(999, mock_async_session)

    assert result is None
    mock_async_session.get.assert_called_once()
