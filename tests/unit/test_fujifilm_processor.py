import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
import dramatiq
import logfire
import anyio # Import anyio because app/tasks/fujifilm_processor.py uses anyio.current_time()
import asyncio

from app.tasks.fujifilm_processor import process_fujifilm_message, _async_process_pipeline, _reception_service, _taller_service
from app.domains.reception.schemas import RawPatientInput, PatientSource, NormalizedPatient
from app.domains.patients.models import Patient
from app.domains.taller.schemas import RawLabValueInput
from app.satellites.fujifilm.parser import FujifilmReading
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def mock_reception_service():
    """Mocks the _reception_service dependency."""
    mock_svc = AsyncMock()
    mock_svc.receive.return_value = MagicMock(
        patient_id=1,
        created=True,
        patient=MagicMock( # Wrap NormalizedPatient in a MagicMock
            id=1, # Explicitly set id here for the mock
            **NormalizedPatient( # Unpack the NormalizedPatient attributes
                id=1, # Also ensure NormalizedPatient has it, though mock will override
                name="POLO",
                species="Canino",
                sex="Macho",
                has_age=True,
                age_value=5,
                age_unit="años",
                age_display="5 años",
                owner_name="OwnerName",
                source=PatientSource.LIS_FUJIFILM
            ).model_dump()
        )
    )
    with patch('app.tasks.fujifilm_processor._reception_service', return_value=mock_svc):
        yield mock_svc

@pytest.fixture
def mock_taller_service():
    """Mocks the _taller_service dependency."""
    mock_svc = AsyncMock()
    mock_svc.create_test_result.return_value = MagicMock(id=100) # Mock TestResult object
    with patch('app.tasks.fujifilm_processor._taller_service', return_value=mock_svc):
        yield mock_svc

@pytest.fixture
def mock_async_session_local():
    """Mocks AsyncSessionLocal to provide an AsyncMock session."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__.return_value = None
    mock_session.commit.return_value = None  # Ensure commit is awaited properly
    mock_session.refresh.return_value = None # Ensure refresh is awaited properly
    # Default DB query returns None (no existing TestResult found)
    mock_db_result = MagicMock()
    mock_db_result.scalars.return_value.first.return_value = None
    mock_session.execute.return_value = mock_db_result
    with patch('app.tasks.fujifilm_processor.AsyncSessionLocal') as MockAsyncSessionLocalClass:
        MockAsyncSessionLocalClass.return_value = mock_session
        yield mock_session

@pytest.fixture(autouse=True)
def mock_logfire():
    """Mocks logfire calls to prevent actual logging during tests."""
    with patch('logfire.info') as mock_info, \
         patch('logfire.warning') as mock_warn, \
         patch('logfire.error') as mock_error:
        yield mock_info, mock_warn, mock_error

@pytest.fixture(autouse=True)
def mock_clinical_standards():
    """Mocks clinical_standards dependencies."""
    with patch('app.tasks.fujifilm_processor.VETERINARY_STANDARDS', {'CRE': {'unit': 'mg/dL'}}), \
         patch('app.tasks.fujifilm_processor.get_parameter_name', return_value='Creatinina'):
        yield

@pytest.fixture(autouse=True)
def mock_reference_range():
    """Mocks get_reference_range."""
    with patch('app.tasks.fujifilm_processor.get_reference_range', return_value='0.5-1.5 mg/dL'):
        yield

# -----------------------------------------------------------------------------
# Tests for process_fujifilm_message (Dramatiq Actor)
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_fujifilm_message_valid_data(
    mock_reception_service, mock_taller_service, mock_async_session_local, mock_logfire
):
    """Scenario: Test process_fujifilm_message with valid data."""
    data = {
        "internal_id": "908",
        "patient_name": "POLO",
        "parameter_code": "CRE",
        "raw_value": "0.87",
        "source": PatientSource.LIS_FUJIFILM.value,
        "received_at": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    }

    with patch('app.tasks.fujifilm_processor.anyio.run', new_callable=MagicMock) as mock_anyio_run:
        process_fujifilm_message(data) # This will now call the mock_pipeline
        mock_anyio_run.assert_called_once() # Verify anyio.run was called

        # Now, we manually call the _async_process_pipeline that was passed to anyio.run
        async_func_to_run, reception_input, internal_id, parameter_code, raw_value_processed = mock_anyio_run.call_args.args
        assert async_func_to_run == _async_process_pipeline
        await async_func_to_run(reception_input, internal_id, parameter_code, raw_value_processed)

        # Assertions on calls made within _async_process_pipeline should go here now
        mock_reception_service.receive.assert_awaited_once_with(
            RawPatientInput(
                raw_string="POLO",
                session_code="908",
                source=PatientSource.LIS_FUJIFILM,
                received_at=reception_input.received_at # Use the actual received_at from the call
            ),
            mock_async_session_local.__aenter__.return_value
        )
        mock_taller_service.create_test_result.assert_awaited_once()
        mock_taller_service.flag_and_store.assert_awaited_once()
        mock_logfire[0].assert_any_call("Fujifilm lab value CRE=0.87 stored in TestResult 100.")

    mock_logfire[0].assert_any_call(
        "Processing Fujifilm reading",
        patient_name="POLO",
        internal_id="908",
        parameter="CRE",
        value="0.87",
        source="LIS_FUJIFILM",
    )

@pytest.mark.asyncio
async def test_process_fujifilm_message_missing_chemistry_values(
    mock_reception_service, mock_taller_service, mock_async_session_local, mock_logfire
):
    """Scenario: Test process_fujifilm_message with missing chemistry values."""
    data = {
        "internal_id": "909",
        "patient_name": "LUPO",
        "source": PatientSource.LIS_FUJIFILM.value,
    }

    with patch('app.tasks.fujifilm_processor.anyio.run', new_callable=MagicMock) as mock_anyio_run:
        process_fujifilm_message(data)
        mock_anyio_run.assert_called_once()

        async_func_to_run, reception_input, internal_id, parameter_code, raw_value_processed = mock_anyio_run.call_args.args
        assert async_func_to_run == _async_process_pipeline
        await async_func_to_run(reception_input, internal_id, parameter_code, raw_value_processed)

        mock_reception_service.receive.assert_awaited_once_with(
            RawPatientInput(
                raw_string="LUPO",
                session_code="909",
                source=PatientSource.LIS_FUJIFILM,
                received_at=reception_input.received_at
            ),
            mock_async_session_local.__aenter__.return_value
        )
        mock_taller_service.create_test_result.assert_not_called()
        mock_taller_service.flag_and_store.assert_not_called()

    mock_logfire[0].assert_any_call(
        "Processing Fujifilm reading",
        patient_name="LUPO",
        internal_id="909",
        parameter="",
        value="",
        source="LIS_FUJIFILM",
    )
    mock_logfire[0].assert_any_call("Fujifilm: No parameter_code or raw_value provided, skipping lab value processing.")

@pytest.mark.asyncio
async def test_process_fujifilm_message_empty_patient_name(
    mock_reception_service, mock_taller_service, mock_async_session_local, mock_logfire
):
    """Test process_fujifilm_message with an empty patient name."""
    data = {
        "internal_id": "910",
        "patient_name": "  ", # Empty name
        "parameter_code": "CRE",
        "raw_value": "0.87",
        "source": PatientSource.LIS_FUJIFILM.value,
    }

    with patch('app.tasks.fujifilm_processor.anyio.run', new_callable=MagicMock) as mock_anyio_run:
        process_fujifilm_message(data)
        mock_anyio_run.assert_not_called() # _async_process_pipeline should not be called for empty name

    mock_reception_service.receive.assert_not_called()
    mock_taller_service.create_test_result.assert_not_called()
    mock_taller_service.flag_and_store.assert_not_called()
    mock_logfire[1].assert_any_call("Fujifilm: empty patient_name — nothing to process") # logfire.warning

@pytest.mark.asyncio
async def test_process_fujifilm_message_invalid_received_at(
    mock_reception_service, mock_taller_service, mock_async_session_local, mock_logfire
):
    """Test process_fujifilm_message with an invalid received_at format."""
    data = {
        "internal_id": "911",
        "patient_name": "CANELA",
        "parameter_code": "CRE",
        "raw_value": "0.87",
        "source": PatientSource.LIS_FUJIFILM.value,
        "received_at": "invalid-timestamp"
    }

    with patch('app.tasks.fujifilm_processor.anyio.run', new_callable=MagicMock) as mock_anyio_run:
        process_fujifilm_message(data)
        mock_anyio_run.assert_called_once()
        
        async_func_to_run, reception_input, internal_id, parameter_code, raw_value_processed = mock_anyio_run.call_args.args
        assert async_func_to_run == _async_process_pipeline
        await async_func_to_run(reception_input, internal_id, parameter_code, raw_value_processed)

        mock_reception_service.receive.assert_awaited_once_with(
            RawPatientInput(
                raw_string="CANELA",
                session_code="911",
                source=PatientSource.LIS_FUJIFILM,
                received_at=reception_input.received_at
            ),
            mock_async_session_local.__aenter__.return_value
        )
        mock_taller_service.create_test_result.assert_awaited_once()
        mock_taller_service.flag_and_store.assert_awaited_once()

    mock_logfire[1].assert_any_call("Fujifilm: invalid received_at 'invalid-timestamp', using now()") # logfire.warning
    mock_logfire[0].assert_any_call(
        "Processing Fujifilm reading",
        patient_name="CANELA",
        internal_id="911",
        parameter="CRE",
        value="0.87",
        source="LIS_FUJIFILM",
    )


@pytest.mark.asyncio
async def test_process_fujifilm_message_raw_value_asterisks(
    mock_reception_service, mock_taller_service, mock_async_session_local, mock_logfire
):
    """Test process_fujifilm_message with raw_value as "****" should set it to None."""
    data = {
        "internal_id": "912",
        "patient_name": "MAX",
        "parameter_code": "CRE",
        "raw_value": "****",
        "source": PatientSource.LIS_FUJIFILM.value,
    }

    with patch('app.tasks.fujifilm_processor.anyio.run', new_callable=MagicMock) as mock_anyio_run:
        process_fujifilm_message(data)
        mock_anyio_run.assert_called_once()

        async_func_to_run, reception_input, internal_id, parameter_code, raw_value_processed = mock_anyio_run.call_args.args
        assert async_func_to_run == _async_process_pipeline
        await async_func_to_run(reception_input, internal_id, parameter_code, raw_value_processed)

        mock_reception_service.receive.assert_awaited_once_with(
            RawPatientInput(
                raw_string="MAX",
                session_code="912",
                source=PatientSource.LIS_FUJIFILM,
                received_at=reception_input.received_at
            ),
            mock_async_session_local.__aenter__.return_value
        )
        mock_taller_service.create_test_result.assert_not_called() # raw_value is None
        mock_taller_service.flag_and_store.assert_not_called()

    mock_logfire[0].assert_any_call(
        "Processing Fujifilm reading",
        patient_name="MAX",
        internal_id="912",
        parameter="CRE",
        value=None, # It becomes None
        source="LIS_FUJIFILM",
    )
    mock_logfire[0].assert_any_call("Fujifilm: No parameter_code or raw_value provided, skipping lab value processing.")


# -----------------------------------------------------------------------------
# Tests for _async_process_pipeline
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_async_process_pipeline_valid_data(
    mock_reception_service, mock_taller_service, mock_async_session_local, mock_logfire
):
    """Scenario: Test _async_process_pipeline with valid data (no chemistry)."""
    reception_input = RawPatientInput(
        raw_string="POLO",
        source=PatientSource.LIS_FUJIFILM,
        received_at=datetime.now(timezone.utc)
    )
    internal_id = "908"
    parameter_code = ""
    raw_value = ""

    await _async_process_pipeline(reception_input, internal_id, parameter_code, raw_value)

    mock_reception_service.receive.assert_awaited_once_with(reception_input, mock_async_session_local.__aenter__.return_value)
    mock_taller_service.create_test_result.assert_not_called()
    mock_taller_service.flag_and_store.assert_not_called()
    mock_logfire[0].assert_any_call("Fujifilm: No parameter_code or raw_value provided, skipping lab value processing.")
    mock_logfire[0].assert_any_call("Fujifilm pipeline completado exitosamente.")

@pytest.mark.asyncio
async def test_async_process_pipeline_with_chemistry_values(
    mock_reception_service, mock_taller_service, mock_async_session_local, mock_logfire
):
    """Scenario: Test _async_process_pipeline with chemistry values."""
    reception_input = RawPatientInput(
        raw_string="POLO",
        source=PatientSource.LIS_FUJIFILM,
        received_at=datetime.now(timezone.utc)
    )
    internal_id = "908"
    parameter_code = "CRE"
    raw_value = "0.87"

    await _async_process_pipeline(reception_input, internal_id, parameter_code, raw_value)

    mock_reception_service.receive.assert_awaited_once()
    mock_taller_service.create_test_result.assert_awaited_once_with(
        patient_id=mock_reception_service.receive.return_value.patient.id,
        test_type="Química Sanguínea",
        test_type_code="CHEM",
        source="LIS_FUJIFILM",
        received_at=reception_input.received_at,
        session=mock_async_session_local.__aenter__.return_value,
    )
    mock_taller_service.flag_and_store.assert_awaited_once()
    mock_logfire[0].assert_any_call("Fujifilm lab value CRE=0.87 stored in TestResult 100.")
    mock_logfire[0].assert_any_call("Fujifilm pipeline completado exitosamente.")

@pytest.mark.asyncio
async def test_async_process_pipeline_non_numeric_raw_value(
    mock_reception_service, mock_taller_service, mock_async_session_local, mock_logfire
):
    """Test _async_process_pipeline with a non-numeric raw_value."""
    reception_input = RawPatientInput(
        raw_string="POLO",
        source=PatientSource.LIS_FUJIFILM,
        received_at=datetime.now(timezone.utc)
    )
    internal_id = "908"
    parameter_code = "CRE"
    raw_value = "HIGH"

    await _async_process_pipeline(reception_input, internal_id, parameter_code, raw_value)

    mock_reception_service.receive.assert_awaited_once()
    mock_taller_service.create_test_result.assert_awaited_once()
    args, kwargs = mock_taller_service.flag_and_store.call_args
    assert kwargs['values'][0].numeric_value is None
    mock_logfire[0].assert_any_call("Fujifilm lab value CRE=HIGH stored in TestResult 100.")

@pytest.mark.asyncio
async def test_async_process_pipeline_exception_handling(
    mock_reception_service, mock_taller_service, mock_async_session_local, mock_logfire
):
    """Test _async_process_pipeline handles exceptions."""
    reception_input = RawPatientInput(
        raw_string="POLO",
        source=PatientSource.LIS_FUJIFILM,
        received_at=datetime.now(timezone.utc)
    )
    internal_id = "908"
    parameter_code = "CRE"
    raw_value = "0.87"

    mock_reception_service.receive.side_effect = Exception("Reception Error")

    with pytest.raises(Exception, match="Reception Error"):
        await _async_process_pipeline(reception_input, internal_id, parameter_code, raw_value)

    mock_logfire[2].assert_any_call( # logfire.error
        "Error crítico en pipeline Fujifilm: Reception Error", exc_info=True
    )


# -----------------------------------------------------------------------------
# Tests for handle_uploaded_file (Fujifilm source fix — Task 1.1)
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_uploaded_file_fujifilm_uses_correct_source(
    mock_async_session_local, mock_logfire
):
    """Scenario: File upload for Fujifilm uses PatientSource.LIS_FUJIFILM.value.

    The source string must be 'LIS_FUJIFILM' (from PatientSource enum), not the
    hardcoded 'FUJIFILM'. This ensures the status dot lights up and the
    Dramatiq actor doesn't crash with ValueError on invalid enum member.
    """
    from app.domains.reception.service import ReceptionService

    fake_records = [
        FujifilmReading(internal_id="908", patient_name="POLO", parameter_code="CRE", raw_value="0.87"),
    ]

    # Patch at the source modules because service.py uses local imports
    with (
        patch('app.satellites.fujifilm.parser.parse_fujifilm_message', return_value=fake_records),
        patch('app.tasks.fujifilm_processor.process_fujifilm_message') as mock_actor,
    ):
        service = ReceptionService()
        await service.handle_uploaded_file(
            b"dummy content", "fujifilm", mock_async_session_local
        )

        mock_actor.send.assert_called_once()
        call_kwargs = mock_actor.send.call_args[0][0]
        assert call_kwargs["source"] == PatientSource.LIS_FUJIFILM.value
        assert call_kwargs["source"] != "FUJIFILM"


# -----------------------------------------------------------------------------
# Tests for _find_or_create_test_result (Task 1.2) and merge behavior (Task 1.3-1.4)
# -----------------------------------------------------------------------------

from app.shared.models.test_result import TestResult
from sqlmodel import select


@pytest.mark.asyncio
async def test_find_or_create_test_result_finds_existing(
    mock_taller_service, mock_async_session_local, mock_logfire
):
    """Scenario: Existing TestResult found by (patient_id, source, received_at) is returned.

    When a reading arrives for a patient+source+received_at combination that
    already has a TestResult, the helper should return the existing one
    without creating a new one.
    """
    from app.tasks.fujifilm_processor import _find_or_create_test_result

    received_at = datetime.now(timezone.utc)
    existing_tr = TestResult(id=42, patient_id=1, source="LIS_FUJIFILM", received_at=received_at)

    # Mock the DB query to return the existing TestResult
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = existing_tr
    mock_async_session_local.execute.return_value = mock_result

    result = await _find_or_create_test_result(
        taller_svc=mock_taller_service,
        patient_id=1,
        source="LIS_FUJIFILM",
        received_at=received_at,
        session=mock_async_session_local,
    )

    assert result.id == 42
    mock_taller_service.create_test_result.assert_not_called()
    mock_logfire[0].assert_any_call(
        f"Found existing TestResult 42 for patient 1"
    )


@pytest.mark.asyncio
async def test_find_or_create_test_result_creates_new(
    mock_taller_service, mock_async_session_local, mock_logfire
):
    """Scenario: No existing TestResult found — creates a new one.

    When a reading arrives for a unique (patient_id, source, received_at)
    combination, the helper should create a fresh TestResult.
    """
    from app.tasks.fujifilm_processor import _find_or_create_test_result

    received_at = datetime.now(timezone.utc)

    # Mock the DB query to return None (no existing TR)
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_async_session_local.execute.return_value = mock_result

    # Mock create_test_result to return a new TestResult
    new_tr = TestResult(id=99, patient_id=1, source="LIS_FUJIFILM", received_at=received_at)
    mock_taller_service.create_test_result.return_value = new_tr

    result = await _find_or_create_test_result(
        taller_svc=mock_taller_service,
        patient_id=1,
        source="LIS_FUJIFILM",
        received_at=received_at,
        session=mock_async_session_local,
    )

    assert result.id == 99
    mock_taller_service.create_test_result.assert_awaited_once_with(
        patient_id=1,
        test_type="Química Sanguínea",
        test_type_code="CHEM",
        source="LIS_FUJIFILM",
        received_at=received_at,
        session=mock_async_session_local,
    )


# -----------------------------------------------------------------------------
# Tests for merge behavior (Task 1.4)
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_async_process_pipeline_merge_same_tr(
    mock_reception_service, mock_taller_service, mock_async_session_local, mock_logfire
):
    """Scenario: Two values with same (patient_id, source, received_at) merge into one TR.

    When a Fujifilm run produces multiple values for the same patient, they should
    all be stored under the same TestResult rather than creating one TR per value.
    """
    received_at = datetime.now(timezone.utc)

    # Set up mock so first pipeline call creates a TR (no existing found)
    # and the TR query returns None
    mock_no_tr = MagicMock()
    mock_no_tr.scalars.return_value.first.return_value = None
    # First execute call → no existing TR
    # Second execute call → no duplicate LabValue
    mock_async_session_local.execute.return_value = mock_no_tr

    # Mock create_test_result to return a known TR
    created_tr = TestResult(id=100, patient_id=1, source="LIS_FUJIFILM", received_at=received_at)
    mock_taller_service.create_test_result.return_value = created_tr

    # Call pipeline for first value (CRE)
    reception_input = RawPatientInput(
        raw_string="POLO",
        source=PatientSource.LIS_FUJIFILM,
        received_at=received_at,
    )
    await _async_process_pipeline(reception_input, "908", "CRE", "0.87")

    # Verify: create_test_result called once for the first value
    assert mock_taller_service.create_test_result.await_count == 1
    # Verify: flag_and_store was called with the first value
    assert mock_taller_service.flag_and_store.await_count == 1
    flag_call_1 = mock_taller_service.flag_and_store.await_args_list[0]
    assert flag_call_1.kwargs["test_result_id"] == 100
    assert flag_call_1.kwargs["values"][0].parameter_code == "CRE"

    # For the second call, mock execute to return the existing TR on first call
    # and None on second call (no duplicate LabValue for BUN)
    mock_existing_tr = MagicMock()
    mock_existing_tr.scalars.return_value.first.return_value = created_tr
    mock_no_dup_lv = MagicMock()
    mock_no_dup_lv.scalars.return_value.first.return_value = None
    mock_async_session_local.execute.side_effect = [mock_existing_tr, mock_no_dup_lv]

    # Call pipeline for second value (BUN) — same patient, same received_at
    await _async_process_pipeline(reception_input, "908", "BUN", "15.2")

    # Reset side_effect for any subsequent test fixture cleanup
    mock_async_session_local.execute.side_effect = None

    # Verify: create_test_result was NOT called again (same TR reused)
    assert mock_taller_service.create_test_result.await_count == 1
    # Verify: flag_and_store was called for the second value
    assert mock_taller_service.flag_and_store.await_count == 2
    flag_call_2 = mock_taller_service.flag_and_store.await_args_list[1]
    assert flag_call_2.kwargs["test_result_id"] == 100
    assert flag_call_2.kwargs["values"][0].parameter_code == "BUN"


@pytest.mark.asyncio
async def test_async_process_pipeline_merge_duplicate_skipped(
    mock_reception_service, mock_taller_service, mock_async_session_local, mock_logfire
):
    """Scenario: Duplicate parameter_code for same TR is skipped with warning.

    If a value with the same parameter_code already exists in the TestResult,
    the duplicate should be skipped and a warning logged.
    """
    received_at = datetime.now(timezone.utc)

    # Set up mock: first pipeline call finds no existing TR
    mock_no_tr = MagicMock()
    mock_no_tr.scalars.return_value.first.return_value = None
    mock_async_session_local.execute.return_value = mock_no_tr

    created_tr = TestResult(id=100, patient_id=1, source="LIS_FUJIFILM", received_at=received_at)
    mock_taller_service.create_test_result.return_value = created_tr

    reception_input = RawPatientInput(
        raw_string="POLO",
        source=PatientSource.LIS_FUJIFILM,
        received_at=received_at,
    )

    # First call: store CRE=0.87
    await _async_process_pipeline(reception_input, "908", "CRE", "0.87")
    assert mock_taller_service.flag_and_store.await_count == 1

    # Second call: mock the TR query to return existing TR
    mock_existing_tr = MagicMock()
    mock_existing_tr.scalars.return_value.first.return_value = created_tr
    # And mock the LabValue duplicate check to return an existing value
    mock_lv_exists = MagicMock()
    mock_lv_exists.scalars.return_value.first.return_value = MagicMock(id=1, parameter_code="CRE")
    # Use side_effect: first call for TR, second call for LabValue check
    mock_async_session_local.execute.side_effect = [mock_existing_tr, mock_lv_exists]

    # Second call: duplicate CRE → should be skipped
    await _async_process_pipeline(reception_input, "908", "CRE", "0.87")

    # Verify: flag_and_store NOT called for duplicate
    assert mock_taller_service.flag_and_store.await_count == 1
    # Verify: warning logged about duplicate
    mock_logfire[1].assert_any_call(
        "Duplicate value for CRE in TestResult 100, skipping"
    )


@pytest.mark.asyncio
async def test_async_process_pipeline_empty_session_code(
    mock_reception_service, mock_taller_service, mock_async_session_local, mock_logfire
):
    """Scenario: Empty session_code (internal_id) still processes correctly.

    When the Fujifilm sends a reading without an internal_id (empty string),
    the pipeline should still work: receive the patient, find/create TestResult
    by (patient_id, source, received_at), and store the lab value.
    """
    received_at = datetime.now(timezone.utc)
    internal_id = ""  # Empty session_code
    reception_input = RawPatientInput(
        raw_string="POLO",
        session_code=internal_id,
        source=PatientSource.LIS_FUJIFILM,
        received_at=received_at,
    )
    parameter_code = "CRE"
    raw_value = "0.87"

    # Mock DB query to return no existing TR (first call)
    mock_no_tr = MagicMock()
    mock_no_tr.scalars.return_value.first.return_value = None
    mock_async_session_local.execute.return_value = mock_no_tr

    created_tr = TestResult(id=100, patient_id=1, source="LIS_FUJIFILM", received_at=received_at)
    mock_taller_service.create_test_result.return_value = created_tr

    await _async_process_pipeline(reception_input, internal_id, parameter_code, raw_value)

    # Verify reception was called with empty session_code
    mock_reception_service.receive.assert_awaited_once_with(
        RawPatientInput(
            raw_string="POLO",
            session_code="",  # Empty session_code is passed through
            source=PatientSource.LIS_FUJIFILM,
            received_at=reception_input.received_at,
        ),
        mock_async_session_local.__aenter__.return_value,
    )

    # Verify TestResult was created (merge by received_at, not session_code)
    mock_taller_service.create_test_result.assert_awaited_once_with(
        patient_id=1,
        test_type="Química Sanguínea",
        test_type_code="CHEM",
        source="LIS_FUJIFILM",
        received_at=received_at,
        session=mock_async_session_local.__aenter__.return_value,
    )

    # Verify flag_and_store stored the value
    mock_taller_service.flag_and_store.assert_awaited_once()
    mock_logfire[0].assert_any_call("Fujifilm lab value CRE=0.87 stored in TestResult 100.")


