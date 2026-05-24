"""Unit tests for PatientArchiveService — archive, restore, and list archived patients."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession
from app.domains.reception.archive_service import PatientArchiveService


@pytest.fixture
def archive_service():
    return PatientArchiveService()


@pytest.fixture
def mock_async_session():
    """Mock AsyncSession for unit-level archive tests."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.commit.return_value = None
    mock_session.refresh.return_value = None
    return mock_session


def _mock_execute_result(rowcount=0, scalar_one_or_none=None, scalars_all=None):
    """Build a MagicMock execute result with configurable return values."""
    result = MagicMock()
    result.rowcount = rowcount
    result.scalar_one_or_none.return_value = scalar_one_or_none
    if scalars_all is not None:
        result.scalars.return_value.all.return_value = scalars_all
    return result


# ── archive_all_active ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_archive_all_active_sets_status(archive_service, mock_async_session):
    """archive_all_active updates waiting_room_status to 'archived' for all active patients."""
    mock_async_session.execute = AsyncMock(
        return_value=_mock_execute_result(rowcount=5)
    )

    count = await archive_service.archive_all_active(mock_async_session)

    assert count == 5
    mock_async_session.execute.assert_called_once()
    mock_async_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_archive_all_active_returns_zero_when_no_active(archive_service, mock_async_session):
    """archive_all_active returns 0 when no active patients exist."""
    mock_async_session.execute = AsyncMock(
        return_value=_mock_execute_result(rowcount=0)
    )

    count = await archive_service.archive_all_active(mock_async_session)

    assert count == 0
    mock_async_session.commit.assert_called_once()


# ── restore_all_archived ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_restore_all_archived_sets_status(archive_service, mock_async_session):
    """restore_all_archived updates waiting_room_status to 'active' for all archived patients."""
    mock_async_session.execute = AsyncMock(
        return_value=_mock_execute_result(rowcount=3)
    )

    count = await archive_service.restore_all_archived(mock_async_session)

    assert count == 3
    mock_async_session.execute.assert_called_once()
    mock_async_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_restore_all_archived_returns_zero_when_none(archive_service, mock_async_session):
    """restore_all_archived returns 0 when no archived patients exist."""
    mock_async_session.execute = AsyncMock(
        return_value=_mock_execute_result(rowcount=0)
    )

    count = await archive_service.restore_all_archived(mock_async_session)

    assert count == 0


# ── restore_single_archived ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_restore_single_archived_flips_status(archive_service, mock_async_session):
    """restore_single_archived sets a patient's status to 'active'."""
    from app.domains.patients.models import Patient
    from datetime import datetime, timezone

    patient = Patient(
        id=42,
        name="Test",
        species="Canino",
        sex="Macho",
        owner_name="Owner",
        source="MANUAL",
        normalized_name="test",
        normalized_owner="owner",
        waiting_room_status="archived",
    )
    mock_async_session.get = AsyncMock(return_value=patient)

    result = await archive_service.restore_single_archived(42, mock_async_session)

    assert result is True
    assert patient.waiting_room_status == "active"
    assert patient.updated_at is not None
    mock_async_session.get.assert_called_once()
    mock_async_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_restore_single_archived_not_found(archive_service, mock_async_session):
    """restore_single_archived returns False for non-existent patient."""
    mock_async_session.get = AsyncMock(return_value=None)

    result = await archive_service.restore_single_archived(999, mock_async_session)

    assert result is False
    mock_async_session.get.assert_called_once()
    mock_async_session.commit.assert_not_called()


# ── get_archived_patients ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_archived_patients_returns_list(archive_service, mock_async_session):
    """get_archived_patients returns a list of dicts for archived patients."""
    from app.domains.patients.models import Patient
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    p1 = Patient(
        id=1, name="Alpha", species="Canino", sex="Macho",
        owner_name="OwnerA", source="MANUAL",
        normalized_name="alpha", normalized_owner="ownera",
        waiting_room_status="archived", session_code="A1",
        created_at=now, updated_at=now,
    )
    p2 = Patient(
        id=2, name="Beta", species="Felino", sex="Hembra",
        owner_name="OwnerB", source="LIS_OZELLE",
        normalized_name="beta", normalized_owner="ownerb",
        waiting_room_status="archived", session_code="B1",
        created_at=now, updated_at=now,
    )

    # Mock the execute for the main query
    main_result = MagicMock()
    main_result.scalars.return_value.all.return_value = [p1, p2]

    # Mock the execute for TestResult sub-query (used inside get_archived_patients)
    tr_result = _mock_execute_result(scalar_one_or_none=10)

    mock_async_session.execute = AsyncMock(side_effect=[main_result, tr_result, tr_result])

    result = await archive_service.get_archived_patients(mock_async_session)

    assert len(result) == 2
    assert result[0]["id"] == 1
    assert result[0]["name"] == "Alpha"
    assert result[0]["waiting_room_status"] == "archived"
    assert result[1]["id"] == 2
    assert result[1]["name"] == "Beta"


@pytest.mark.asyncio
async def test_get_archived_patients_empty(archive_service, mock_async_session):
    """get_archived_patients returns empty list when no patients are archived."""
    main_result = MagicMock()
    main_result.scalars.return_value.all.return_value = []

    mock_async_session.execute = AsyncMock(return_value=main_result)

    result = await archive_service.get_archived_patients(mock_async_session)

    assert result == []
    mock_async_session.execute.assert_called_once()
