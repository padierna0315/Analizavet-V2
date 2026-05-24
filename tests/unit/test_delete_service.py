"""Unit tests for PatientDeleteService — delete patient from waiting room with cascade."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession
from app.domains.reception.delete_service import PatientDeleteService


@pytest.fixture
def delete_service():
    return PatientDeleteService()


@pytest.fixture
def mock_async_session():
    """Mock AsyncSession for unit-level delete tests."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.commit.return_value = None
    mock_session.refresh.return_value = None
    return mock_session


def _mock_execute_result(scalar_one_or_none=None):
    """Build a MagicMock execute result."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_one_or_none
    return result


# ── delete_patient_from_waiting_room ────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_patient_found_and_deleted(delete_service, mock_async_session):
    """Deleting an existing patient returns True and calls session.delete."""
    from app.domains.patients.models import Patient

    patient = Patient(
        id=1, name="Firulais", species="Canino", sex="Macho",
        owner_name="Owner", source="MANUAL",
        normalized_name="firulais", normalized_owner="owner",
    )
    mock_async_session.execute = AsyncMock(
        return_value=_mock_execute_result(scalar_one_or_none=patient)
    )
    mock_async_session.delete = AsyncMock()

    result = await delete_service.delete_patient_from_waiting_room(1, mock_async_session)

    assert result is True
    mock_async_session.delete.assert_called_once_with(patient)
    mock_async_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_delete_patient_not_found(delete_service, mock_async_session):
    """Deleting a non-existent patient returns False and does NOT call delete."""
    mock_async_session.execute = AsyncMock(
        return_value=_mock_execute_result(scalar_one_or_none=None)
    )
    mock_async_session.delete = AsyncMock()

    result = await delete_service.delete_patient_from_waiting_room(999, mock_async_session)

    assert result is False
    mock_async_session.delete.assert_not_called()
    mock_async_session.commit.assert_not_called()
