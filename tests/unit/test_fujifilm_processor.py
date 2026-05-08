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
                source=PatientSource.LIS_FUJIFILM,
                received_at=reception_input.received_at # Use the actual received_at from the call
            ),
            mock_async_session_local.__aenter__.return_value
        )
        mock_taller_service.create_test_result.assert_awaited_once()
        mock_taller_service.flag_and_store.assert_awaited_once()
        mock_logfire[0].assert_any_call("Fujifilm lab value processed and stored successfully.")

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
    mock_logfire[0].assert_any_call("Fujifilm lab value processed and stored successfully.")
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
    mock_logfire[0].assert_any_call("Fujifilm lab value processed and stored successfully.")

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