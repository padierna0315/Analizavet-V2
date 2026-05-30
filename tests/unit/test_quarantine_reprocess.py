"""Tests for quarantine reprocessing actor (T6/T10)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.reception.schemas import PatientSource
from app.shared.models.data_quarantine import DataQuarantine
from app.domains.patients.models import Patient


@pytest.fixture
def mock_async_session_q():
    """Mocks AsyncSession for quarantine reprocessing tests."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__.return_value = None
    mock_session.commit.return_value = None
    mock_session.refresh.return_value = None
    return mock_session


@pytest.mark.asyncio
async def test_reprocess_quarantine_attaches_to_confirmed_patient(
    mock_async_session_q,
):
    """When a quarantined item is reprocessed after AppSheet confirms the
    patient, it must attach to the confirmed patient and return created=False.
    """
    from app.tasks.quarantine_reprocess import _async_reprocess_quarantined
    from app.domains.reception.intake_service import PatientIntakeService

    quarantine = DataQuarantine(
        id=1,
        source=PatientSource.LIS_OZELLE.value,
        raw_data="M5 KIARA",
        received_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        rejection_reason="awaiting_appsheet",
        session_code="M5",
        status="pending",
    )

    # Mock the DB query to return the quarantine record
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = quarantine
    mock_async_session_q.execute = AsyncMock(return_value=mock_result)

    # Mock PatientIntakeService to simulate confirmed patient attach
    with patch.object(
        PatientIntakeService, "receive", new_callable=AsyncMock
    ) as mock_receive:
        from app.domains.reception.schemas import BaulResult, NormalizedPatient

        normal = NormalizedPatient(
            name="Kiara",
            species="Felino",
            sex="Hembra",
            has_age=True,
            age_value=7,
            age_unit="años",
            age_display="7 años",
            owner_name="María",
            source=PatientSource.LIS_OZELLE,
        )
        mock_receive.return_value = BaulResult(
            patient_id=42, created=False, patient=normal,
        )

        with patch(
            "app.tasks.quarantine_reprocess.AsyncSessionLocal",
            return_value=mock_async_session_q,
        ):
            await _async_reprocess_quarantined(quarantine_id=1)

        # Verify receive() was called with correct RawPatientInput
        mock_receive.assert_awaited_once()
        call_input = mock_receive.await_args[0][0]
        assert call_input.raw_string == "M5 KIARA"
        assert call_input.source == PatientSource.LIS_OZELLE
        assert call_input.session_code == "M5"


@pytest.mark.asyncio
async def test_reprocess_quarantine_handles_missing_record(
    mock_async_session_q,
):
    """When the quarantine record is not found, the actor must log a warning
    and return cleanly without raising."""
    from app.tasks.quarantine_reprocess import _async_reprocess_quarantined

    # Mock DB query to return None (record not found)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_async_session_q.execute = AsyncMock(return_value=mock_result)

    with patch(
        "app.tasks.quarantine_reprocess.AsyncSessionLocal",
        return_value=mock_async_session_q,
    ):
        # Should not raise
        await _async_reprocess_quarantined(quarantine_id=999)


@pytest.mark.asyncio
async def test_reprocess_quarantine_logs_error_on_receive_failure(
    mock_async_session_q,
):
    """When receive() raises an exception, the actor must log the error
    but NOT re-raise — the Dramatiq retry handles it."""
    from app.tasks.quarantine_reprocess import _async_reprocess_quarantined
    from app.domains.reception.intake_service import PatientIntakeService

    quarantine = DataQuarantine(
        id=2,
        source=PatientSource.LIS_FUJIFILM.value,
        raw_data="F2 POLO",
        received_at=datetime.now(timezone.utc),
        rejection_reason="awaiting_appsheet",
        session_code="F2",
        status="pending",
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = quarantine
    mock_async_session_q.execute = AsyncMock(return_value=mock_result)

    with patch.object(
        PatientIntakeService, "receive", new_callable=AsyncMock
    ) as mock_receive:
        mock_receive.side_effect = Exception("DB error")

        with patch(
            "app.tasks.quarantine_reprocess.AsyncSessionLocal",
            return_value=mock_async_session_q,
        ):
            # Should NOT raise — errors are logged, not re-raised
            await _async_reprocess_quarantined(quarantine_id=2)

        mock_receive.assert_awaited_once()
