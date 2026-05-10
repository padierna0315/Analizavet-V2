"""
Integration test for Fujifilm DRI-CHEM NX600 pipeline.

Tests the full flow: parsing -> actor dispatch -> merge processing.

Key scenarios:
- Multiple chemistry values for same patient -> 1 TestResult (merge)
- Different patients -> separate TestResults
- Source string is LIS_FUJIFILM (not raw "FUJIFILM")
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from app.satellites.fujifilm.parser import parse_fujifilm_message, FujifilmReading
from app.tasks.fujifilm_processor import _async_process_pipeline
from app.domains.reception.schemas import RawPatientInput, PatientSource
from sqlalchemy.ext.asyncio import AsyncSession


# ── Sample Fujifilm data ──────────────────────────────────────────────────────

# Simulates a Fujifilm .txt upload with 3 chemistry values for patient "POLO" (ID 908)
# and 1 value for patient "LUNA" (ID 909)
SAMPLE_FUJIFILM_TXT = (
    "S,NORMAL,10-05-2026,14:30,908,POLO,CRE-PS,=,0.87,mg/dL,CRE,BUN-PS,=,15.2,mg/dL,BUN,"
    "GLU-PS,=,95.0,mg/dL,GLU\r\n"
    "S,NORMAL,10-05-2026,14:31,909,LUNA,CRE-PS,=,1.2,mg/dL,CRE\r\n"
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_reception_service():
    """Mocks the _reception_service dependency. Returns patient IDs by session_code."""
    mock_svc = AsyncMock()

    def get_receive_side_effect(*args, **kwargs):
        raw_input = args[0] if args else kwargs.get("raw_input")
        internal_id = raw_input.session_code if raw_input else "908"
        patient_ids = {"908": 1, "909": 2}
        pid = patient_ids.get(internal_id, 99)

        return MagicMock(
            patient_id=pid,
            created=True,
            patient=MagicMock(
                id=pid,
                name=raw_input.raw_string if raw_input else "POLO",
                species="Canino",
                sex="Macho",
                has_age=False,
                age_value=None,
                age_unit=None,
                age_display=None,
                owner_name="",
                source=PatientSource.LIS_FUJIFILM,
            ),
        )

    mock_svc.receive.side_effect = get_receive_side_effect

    with patch("app.tasks.fujifilm_processor._reception_service", return_value=mock_svc):
        yield mock_svc


@pytest.fixture
def mock_taller_service():
    """Mocks _taller_service. create_test_result returns a mock TR with unique ID."""
    mock_svc = AsyncMock()
    mock_svc.create_test_result.side_effect = (
        lambda patient_id, test_type, test_type_code, source, received_at, session:
        MagicMock(id=patient_id * 100)
    )
    with patch("app.tasks.fujifilm_processor._taller_service", return_value=mock_svc):
        yield mock_svc


@pytest.fixture
def mock_async_session():
    """Mocks AsyncSessionLocal with a simple controllable DB session.

    Default: all DB queries return None (no existing TR, no duplicate LV).
    Individual tests override execute.side_effect or return_value as needed.
    """
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__.return_value = None
    mock_session.commit.return_value = None
    mock_session.refresh.return_value = None

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_session.execute.return_value = mock_result

    with patch("app.tasks.fujifilm_processor.AsyncSessionLocal") as MockSessionClass:
        MockSessionClass.return_value = mock_session
        yield mock_session


@pytest.fixture(autouse=True)
def mock_logfire():
    """Mocks logfire to prevent actual logging in tests."""
    with (
        patch("logfire.info") as mock_info,
        patch("logfire.warning") as mock_warn,
        patch("logfire.error") as mock_error,
    ):
        yield mock_info, mock_warn, mock_error


@pytest.fixture(autouse=True)
def mock_clinical_standards():
    """Mocks clinical_standards for deterministic test results."""
    with (
        patch(
            "app.tasks.fujifilm_processor.VETERINARY_STANDARDS",
            {
                "CRE": {"unit": "mg/dL"},
                "BUN": {"unit": "mg/dL"},
                "GLU": {"unit": "mg/dL"},
            },
        ),
        patch(
            "app.tasks.fujifilm_processor.get_parameter_name",
            side_effect=lambda code, short=False: {
                "CRE": "Creatinina",
                "BUN": "Nitrógeno Ureico",
                "GLU": "Glucosa",
            }.get(code, code),
        ),
        patch(
            "app.tasks.fujifilm_processor.get_reference_range",
            return_value="0.5-1.5 mg/dL",
        ),
    ):
        yield


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _run_pipeline_for_record(
    record: FujifilmReading,
    received_at: datetime,
):
    """Helper: build a RawPatientInput and run the pipeline for a single reading."""
    reception_input = RawPatientInput(
        raw_string=record.patient_name,
        session_code=record.internal_id,
        source=PatientSource.LIS_FUJIFILM,
        received_at=received_at,
    )
    await _async_process_pipeline(
        reception_input,
        record.internal_id,
        record.parameter_code,
        record.raw_value,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestFujifilmPipeline:
    """Integration tests for the full Fujifilm pipeline: parse -> process -> merge."""

    @pytest.mark.asyncio
    async def test_full_pipeline_parse_and_process(
        self,
        mock_reception_service,
        mock_taller_service,
        mock_async_session,
        mock_logfire,
    ):
        """Scenario: Parse Fujifilm .txt and process all readings.

        GIVEN a Fujifilm .txt file with 4 readings (3 for POLO, 1 for LUNA)
        WHEN parsed and processed through the pipeline
        THEN all readings are stored
        AND each unique (patient_id, source, received_at) gets one TestResult
        """
        # Step 1: Parse the Fujifilm file
        records = parse_fujifilm_message(SAMPLE_FUJIFILM_TXT)
        assert len(records) == 4, f"Expected 4 readings, got {len(records)}"

        # Step 2: Mock _find_or_create_test_result to simulate merge behavior.
        # First call (POLO): no existing TR -> create new (calls taller_svc.create_test_result)
        # Second call (POLO): existing TR found -> return cached
        # Third call (POLO): existing TR found -> return cached
        # Fourth call (LUNA): no existing TR (different patient) -> create new
        created_trs: dict[int, MagicMock] = {}

        async def mock_find_or_create(taller_svc, patient_id, source, received_at, session):
            if patient_id in created_trs:
                return created_trs[patient_id]
            tr = await taller_svc.create_test_result(
                patient_id=patient_id, test_type="Química Sanguínea",
                test_type_code="CHEM", source=source,
                received_at=received_at, session=session,
            )
            created_trs[patient_id] = tr
            return tr

        with patch(
            "app.tasks.fujifilm_processor._find_or_create_test_result",
            side_effect=mock_find_or_create,
        ):
            received_at = datetime.now(timezone.utc)
            for record in records:
                await _run_pipeline_for_record(record, received_at)

        # Step 3: Verify merge behavior
        # 3 POLO readings share patient_id=1 -> 1 TR
        # 1 LUNA reading has patient_id=2 -> 1 TR
        # Total: 2 create_test_result calls
        assert (
            mock_taller_service.create_test_result.await_count == 2
        ), (
            f"Expected 2 create_test_result calls (one per unique patient), "
            f"got {mock_taller_service.create_test_result.await_count}"
        )

        # Step 4: Verify flag_and_store was called for each value
        assert (
            mock_taller_service.flag_and_store.await_count == 4
        ), (
            f"Expected 4 flag_and_store calls (one per reading), "
            f"got {mock_taller_service.flag_and_store.await_count}"
        )

    @pytest.mark.asyncio
    async def test_merge_multiple_values_same_patient(
        self,
        mock_reception_service,
        mock_taller_service,
        mock_async_session,
        mock_logfire,
    ):
        """Scenario: 3 values for POLO merge into 1 TestResult.

        GIVEN three Fujifilm readings for the same patient (POLO, ID 908)
        WHEN processed with the same (patient_id, source, received_at)
        THEN only 1 TestResult is created
        AND 3 LabValues are stored
        """
        created_trs: dict[int, MagicMock] = {}

        async def mock_find_or_create(taller_svc, patient_id, source, received_at, session):
            if patient_id in created_trs:
                return created_trs[patient_id]
            tr = await taller_svc.create_test_result(
                patient_id=patient_id, test_type="Química Sanguínea",
                test_type_code="CHEM", source=source,
                received_at=received_at, session=session,
            )
            created_trs[patient_id] = tr
            return tr

        with patch(
            "app.tasks.fujifilm_processor._find_or_create_test_result",
            side_effect=mock_find_or_create,
        ):
            received_at = datetime.now(timezone.utc)
            readings = [
                FujifilmReading(internal_id="908", patient_name="POLO", parameter_code="CRE", raw_value="0.87"),
                FujifilmReading(internal_id="908", patient_name="POLO", parameter_code="BUN", raw_value="15.2"),
                FujifilmReading(internal_id="908", patient_name="POLO", parameter_code="GLU", raw_value="95.0"),
            ]
            for record in readings:
                await _run_pipeline_for_record(record, received_at)

        # create_test_result should be called only ONCE
        assert (
            mock_taller_service.create_test_result.await_count == 1
        ), f"Expected 1 create_test_result call, got {mock_taller_service.create_test_result.await_count}"

        # flag_and_store should be called for each unique value
        assert (
            mock_taller_service.flag_and_store.await_count == 3
        ), f"Expected 3 flag_and_store calls, got {mock_taller_service.flag_and_store.await_count}"

    @pytest.mark.asyncio
    async def test_different_patients_separate_test_results(
        self,
        mock_reception_service,
        mock_taller_service,
        mock_async_session,
        mock_logfire,
    ):
        """Scenario: Different patients get separate TestResults.

        GIVEN readings for two different patients
        WHEN processed
        THEN each patient gets its own TestResult
        """
        created_trs: dict[int, MagicMock] = {}

        async def mock_find_or_create(taller_svc, patient_id, source, received_at, session):
            if patient_id in created_trs:
                return created_trs[patient_id]
            tr = await taller_svc.create_test_result(
                patient_id=patient_id, test_type="Química Sanguínea",
                test_type_code="CHEM", source=source,
                received_at=received_at, session=session,
            )
            created_trs[patient_id] = tr
            return tr

        with patch(
            "app.tasks.fujifilm_processor._find_or_create_test_result",
            side_effect=mock_find_or_create,
        ):
            received_at = datetime.now(timezone.utc)
            readings = [
                FujifilmReading(internal_id="908", patient_name="POLO", parameter_code="CRE", raw_value="0.87"),
                FujifilmReading(internal_id="909", patient_name="LUNA", parameter_code="CRE", raw_value="1.2"),
            ]
            for record in readings:
                await _run_pipeline_for_record(record, received_at)

        # Each patient gets their own TestResult
        assert (
            mock_taller_service.create_test_result.await_count == 2
        ), f"Expected 2 create_test_result calls, got {mock_taller_service.create_test_result.await_count}"

    @pytest.mark.asyncio
    async def test_source_value_is_lis_fujifilm(
        self,
        mock_reception_service,
        mock_taller_service,
        mock_async_session,
        mock_logfire,
    ):
        """Scenario: Source value is 'LIS_FUJIFILM', not raw 'FUJIFILM'.

        GIVEN a Fujifilm reading
        WHEN processed through the pipeline
        THEN the source passed to create_test_result is 'LIS_FUJIFILM'
        """
        received_at = datetime.now(timezone.utc)

        # Patch _find_or_create_test_result so it actually calls create_test_result
        async def mock_find_or_create(taller_svc, patient_id, source, received_at, session):
            return await taller_svc.create_test_result(
                patient_id=patient_id, test_type="Química Sanguínea",
                test_type_code="CHEM", source=source,
                received_at=received_at, session=session,
            )

        with patch(
            "app.tasks.fujifilm_processor._find_or_create_test_result",
            side_effect=mock_find_or_create,
        ):
            await _run_pipeline_for_record(
                FujifilmReading(internal_id="908", patient_name="POLO", parameter_code="CRE", raw_value="0.87"),
                received_at,
            )

        # Verify source in create_test_result call
        call_args = mock_taller_service.create_test_result.await_args
        assert call_args is not None, "create_test_result was not called"
        assert call_args.kwargs["source"] == "LIS_FUJIFILM"
