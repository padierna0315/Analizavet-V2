import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession
from app.domains.patients.models import Patient
from app.domains.reception.schemas import RawPatientInput, PatientSource, NormalizedPatient
from app.domains.reception.service import ReceptionService, _sanitize_patient_age
import json
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional


class MockPatient:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        self._sources_received_list = [] # Internal list
    
    @property
    def sources_received(self):
        return self._sources_received_list


class MockBaulResult:
    def __init__(self, patient_id, created, patient):
        self.patient_id = patient_id
        self.created = created
        self.patient = patient


@pytest.fixture
def mock_async_session():
    """Mocks AsyncSession to ensure commit and refresh are awaited."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.commit.return_value = None
    mock_session.refresh.return_value = None
    
    # Setup default execute behavior (return empty result)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    # Also default scalars().first() to None — needed for ozelle/fuji match queries
    mock_result.scalars.return_value.first.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)
    
    return mock_session


def setup_mock_session_execute(mock_session, return_value=None, scalar_first_return=None):
    """Helper to configure session.execute().
    
    Args:
        return_value: Value for scalar_one_or_none()
        scalar_first_return: Value for scalars().first() (defaults to return_value)
    """
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = return_value
    mock_result.scalars.return_value.first.return_value = scalar_first_return if scalar_first_return is not None else return_value
    mock_session.execute.return_value = mock_result


@pytest.mark.asyncio
async def test_receive_new_patient_creates_record(mock_async_session):
    """Test that receiving a new patient creates a new record."""
    # Setup
    service = ReceptionService()

    # Create a real patient instance
    mock_patient_instance = Patient(
        id=1,
        name="Firulais",
        species="Canino",
        sex="Macho",
        has_age=True,
        age_value=3,
        age_unit="años",
        age_display="3 años",
        owner_name="Juan Pérez",
        source=PatientSource.LIS_OZELLE.value,
        normalized_name="firulais",
        normalized_owner="juan perez",
        sources_received=[]
    )

    # Mock session.get to return our mock patient
    mock_async_session.get.return_value = mock_patient_instance

    baul_register_return_value = MockBaulResult(
        patient_id=1,
        created=True,
        patient=mock_patient_instance
    )

    # Mock the BaulService _find_existing to return None (no existing patient)
    # and register to return a new patient
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(service._baul, '_find_existing', AsyncMock(return_value=None))
        mp.setattr(service._baul, 'register', AsyncMock(return_value=baul_register_return_value))


        # Execute
        raw_input = RawPatientInput(
            raw_string="firulais canino 3a Juan Pérez",
            source=PatientSource.LIS_OZELLE,
            received_at=datetime.now(timezone.utc)
        )

        result = await service.receive(raw_input, mock_async_session)

        # Verify
        assert result.created is True
        assert result.patient_id == 1
        assert result.patient.name == "Firulais"


@pytest.mark.asyncio
async def test_receive_existing_patient_updates_demographic_data(mock_async_session):
    """Test that receiving data for an existing patient updates demographic fields."""
    # Setup
    service = ReceptionService()
    # mock_session = mock_async_session # Removed this line
    
    # Create an existing patient record (from Ozelle)
    existing_patient = Patient(
        id=1,
        name="Firulais",  # Original name from Ozelle
        species="Canino",
        sex="Macho",
        owner_name="Juan Pérez",  # Original owner from Ozelle
        has_age=True,
        age_value=3,
        age_unit="años",
        age_display="3 años",
        source=PatientSource.LIS_OZELLE.value,
        normalized_name="firulais",
        normalized_owner="juan perez",
        sources_received=[PatientSource.LIS_OZELLE.value]
    )
    
    # Mock the _find_existing method to return our existing patient
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(service._baul, '_find_existing', AsyncMock(return_value=existing_patient))
        mp.setattr(service._baul, 'register', AsyncMock())  # Should not be called
        
        # Execute - receive JSON data with different demographic info
        raw_input = RawPatientInput(
            raw_string="tommy canino 5a María García",  # Different name and owner
            source=PatientSource.MANUAL,  # JSON source treated as MANUAL for now
            received_at=datetime.now(timezone.utc)
        )
        
        result = await service.receive(raw_input, mock_async_session)
        
        # Verify
        assert result.created is False  # Should not create new patient
        assert result.patient_id == 1   # Should return existing patient ID
        
        # Verify the patient was updated with JSON data (demographic fields)
        assert existing_patient.name == "Tommy"  # Updated from JSON
        assert existing_patient.owner_name == "María García"  # Updated from JSON
        assert existing_patient.species == "Canino"  # Should remain same
        assert existing_patient.sex == "Macho"  # Should remain same
        assert existing_patient.has_age == True  # Should remain same
        assert existing_patient.age_value == 5  # Updated from JSON
        assert existing_patient.age_unit == "años"  # Should remain same
        assert existing_patient.age_display == "5 años"  # Updated from JSON
        
        # Verify sources_received was updated to include both sources
        sources_received = existing_patient.sources_received
        assert PatientSource.LIS_OZELLE.value in sources_received
        assert PatientSource.MANUAL.value in sources_received
        
        # Verify session was committed
        mock_async_session.commit.assert_awaited()
        mock_async_session.refresh.assert_awaited_with(existing_patient)


@pytest.mark.asyncio
async def test_receive_existing_patient_ozelle_data_preserved(mock_async_session):
    """Test that Ozelle data is preserved when receiving JSON data later."""
    # Setup
    service = ReceptionService()
    # mock_session = mock_async_session
    
    # Create an existing patient record (from Ozelle) with lab data association
    existing_patient = Patient(
        id=1,
        name="Firulais",
        species="Canino",
        sex="Macho",
        owner_name="Juan Pérez",
        has_age=True,
        age_value=3,
        age_unit="años",
        age_display="3 años",
        source=PatientSource.LIS_OZELLE.value,
        normalized_name="firulais",
        normalized_owner="juan perez",
        sources_received=[PatientSource.LIS_OZELLE.value]
    )
    
    # Mock the _find_existing method to return our existing patient
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(service._baul, '_find_existing', AsyncMock(return_value=existing_patient))
        mp.setattr(service._baul, 'register', AsyncMock())  # Should not be called
        
        # Execute - receive JSON data
        raw_input = RawPatientInput(
            raw_string="tommy canino 5a María García",
            source=PatientSource.MANUAL,  # JSON source
            received_at=datetime.now(timezone.utc)
        )
        
        result = await service.receive(raw_input, mock_async_session)
        
        # Verify Ozelle-related fields are preserved (though in this simplified model,
        # we don't have explicit lab data fields on Patient - that's in TestResult)
        # The key point is that we're not creating a new patient, so any existing
        # TestResult/Ozelle data would remain associated with this patient
        assert result.created is False
        assert result.patient_id == 1


@pytest.mark.asyncio
async def test_receive_same_source_twice_does_not_duplicate_sources(mock_async_session):
    """Test that receiving data from the same source twice doesn't duplicate sources_received."""
    # Setup
    service = ReceptionService()
    # mock_session = mock_async_session
    
    # Create an existing patient record
    existing_patient = Patient(
        id=1,
        name="Firulais",
        species="Canino",
        sex="Macho",
        owner_name="Juan Pérez",
        has_age=True,
        age_value=3,
        age_unit="años",
        age_display="3 años",
        source=PatientSource.LIS_OZELLE.value,
        normalized_name="firulais",
        normalized_owner="juan perez",
        sources_received=[PatientSource.LIS_OZELLE.value]
    )
    
    # Mock the _find_existing method to return our existing patient
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(service._baul, '_find_existing', AsyncMock(return_value=existing_patient))
        mp.setattr(service._baul, 'register', AsyncMock())  # Should not be called
        
        # Execute - receive Ozelle data twice
        raw_input = RawPatientInput(
            raw_string="firulais canino 3a Juan Pérez",
            source=PatientSource.LIS_OZELLE,
            received_at=datetime.now(timezone.utc)
        )
        
        result = await service.receive(raw_input, mock_async_session)
        
        # Verify
        assert result.created is False
        assert result.patient_id == 1
        
        # Verify sources_received still only contains one entry for LIS_OZELLE
        sources_received = existing_patient.sources_received
        assert sources_received.count(PatientSource.LIS_OZELLE.value) == 1
        assert len(sources_received) == 1


# ── Ozelle match tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ozelle_match_finds_existing_patient_by_name(mock_async_session):
    """Ozelle data should match existing patient by normalized_name when session_code is None."""
    service = ReceptionService()

    # Create an existing patient with AppSheet as source
    existing_patient = Patient(
        id=1,
        name="Rex",
        species="Canino",
        sex="Macho",
        owner_name="Juan Pérez",
        has_age=True,
        age_value=3,
        age_unit="años",
        age_display="3 años",
        source=PatientSource.APPSHEET.value,
        normalized_name="rex",
        normalized_owner="juan perez",
        sources_received=[PatientSource.APPSHEET.value],
    )

    # First execute → session_code lookup → None (no match)
    # Second execute → Ozelle name query → returns existing_patient
    empty_result = MagicMock()
    empty_result.scalar_one_or_none.return_value = None

    ozelle_result = MagicMock()
    ozelle_result.scalars.return_value.first.return_value = existing_patient

    mock_async_session.execute = AsyncMock(side_effect=[empty_result, ozelle_result])

    # Mock _find_existing to ensure it is NOT called (Ozelle match returns early)
    mp = pytest.MonkeyPatch()
    mp.setattr(service._baul, "_find_existing", AsyncMock())

    try:
        raw_input = RawPatientInput(
            raw_string="rex canino 3a Juan Pérez",
            source=PatientSource.LIS_OZELLE,
            received_at=datetime.now(timezone.utc),
        )

        result = await service.receive(raw_input, mock_async_session)

        # Should NOT create a new patient
        assert result.created is False
        assert result.patient_id == 1

        # Returned NormalizedPatient must have DB demographics, not normalized values
        assert result.patient.name == "Rex"
        assert result.patient.species == "Canino"
        assert result.patient.owner_name == "Juan Pérez"

        # sources_received should now include LIS_OZELLE
        assert PatientSource.LIS_OZELLE.value in existing_patient.sources_received
        assert PatientSource.APPSHEET.value in existing_patient.sources_received

        # _find_existing must NOT be called — Ozelle match returned early
        service._baul._find_existing.assert_not_called()
    finally:
        mp.undo()


@pytest.mark.asyncio
async def test_ozelle_match_does_not_overwrite_demographics(mock_async_session):
    """Ozelle match must preserve existing species/age/owner from DB, not overwrite."""
    service = ReceptionService()

    # Existing patient from AppSheet with specific demographics
    existing_patient = Patient(
        id=1,
        name="Luna",
        species="Felino",
        sex="Hembra",
        owner_name="María García",
        has_age=True,
        age_value=5,
        age_unit="años",
        age_display="5 años",
        source=PatientSource.APPSHEET.value,
        normalized_name="luna",
        normalized_owner="maria garcia",
        sources_received=[PatientSource.APPSHEET.value],
    )

    # First execute → session_code lookup → None
    # Second execute → Ozelle name query → returns existing_patient
    empty_result = MagicMock()
    empty_result.scalar_one_or_none.return_value = None

    ozelle_result = MagicMock()
    ozelle_result.scalars.return_value.first.return_value = existing_patient

    mock_async_session.execute = AsyncMock(side_effect=[empty_result, ozelle_result])

    # Mock _find_existing to ensure it is NOT called
    mp = pytest.MonkeyPatch()
    mp.setattr(service._baul, "_find_existing", AsyncMock())

    try:
        # Raw input normalizes to Canino/Pedro but Ozelle match bypasses that
        # and uses DB data (Felino/María García)
        raw_input = RawPatientInput(
            raw_string="luna canino 5a Pedro",
            source=PatientSource.LIS_FILE,  # LIS_FILE also triggers ozelle_match
            received_at=datetime.now(timezone.utc),
        )

        result = await service.receive(raw_input, mock_async_session)

        # Patient demographics must remain intact (not overwritten by Ozelle data)
        assert existing_patient.species == "Felino"  # NOT "Canino" (from normalizer)
        assert existing_patient.sex == "Hembra"  # NOT "Macho" (from normalizer)
        assert existing_patient.owner_name == "María García"  # NOT "Pedro"
        assert existing_patient.has_age is True
        assert existing_patient.age_value == 5
        assert existing_patient.age_display == "5 años"

        # Returned NormalizedPatient must reflect DB values
        assert result.patient.name == "Luna"
        assert result.patient.species == "Felino"  # From DB, not normalizer's "Canino"
        assert result.patient.owner_name == "María García"

        # LIS_FILE source should have been added
        assert PatientSource.LIS_FILE.value in existing_patient.sources_received

        # _find_existing must NOT be called
        service._baul._find_existing.assert_not_called()
    finally:
        mp.undo()


@pytest.mark.asyncio
async def test_ozelle_match_fallthrough_when_name_does_not_match(mock_async_session):
    """Ozelle source with no name match should fall through to _find_existing."""
    service = ReceptionService()

    # Create an existing patient that _find_existing will return
    existing_patient = Patient(
        id=1,
        name="Rex",
        species="Canino",
        sex="Macho",
        owner_name="Juan Pérez",
        has_age=True,
        age_value=3,
        age_unit="años",
        age_display="3 años",
        source=PatientSource.APPSHEET.value,
        normalized_name="rex",
        normalized_owner="juan perez",
        sources_received=[PatientSource.APPSHEET.value],
    )

    # First execute → session_code lookup → None (no match)
    # Second execute → Ozelle name query → None (name "rex" not found)
    empty_result = MagicMock()
    empty_result.scalar_one_or_none.return_value = None

    ozelle_no_match = MagicMock()
    ozelle_no_match.scalar_one_or_none.return_value = None
    ozelle_no_match.scalars.return_value.first.return_value = None

    mock_async_session.execute = AsyncMock(side_effect=[empty_result, ozelle_no_match])

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(service._baul, "_find_existing", AsyncMock(return_value=existing_patient))
        mp.setattr(service._baul, "register", AsyncMock())

        raw_input = RawPatientInput(
            raw_string="rex canino 3a Juan Pérez",
            source=PatientSource.LIS_OZELLE,
            received_at=datetime.now(timezone.utc),
        )

        result = await service.receive(raw_input, mock_async_session)

        # Should have found patient via _find_existing
        assert result.created is False
        assert result.patient_id == 1

        # _find_existing MUST have been called (Ozelle match didn't find by name)
        service._baul._find_existing.assert_awaited_once()

        # Merge guard should protect demographics for LIS_OZELLE
        assert existing_patient.species == "Canino"


@pytest.mark.asyncio
async def test_fujifilm_merge_guard_protects_demographics(mock_async_session):
    """Fujifilm data in the generic merge path must NOT overwrite demographics."""
    service = ReceptionService()

    # Existing patient with specific demographics
    existing_patient = Patient(
        id=1,
        name="Rex",
        species="Canino",
        sex="Macho",
        owner_name="Juan Pérez",
        has_age=True,
        age_value=3,
        age_unit="años",
        age_display="3 años",
        source=PatientSource.APPSHEET.value,
        normalized_name="rex",
        normalized_owner="juan perez",
        sources_received=[PatientSource.APPSHEET.value],
    )

    # First execute → session_code lookup → None
    # Second execute → Fuji name query → None (fuji_match doesn't find)
    empty_result = MagicMock()
    empty_result.scalar_one_or_none.return_value = None
    empty_result.scalars.return_value.first.return_value = None

    mock_async_session.execute = AsyncMock(side_effect=[empty_result, empty_result])

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(service._baul, "_find_existing", AsyncMock(return_value=existing_patient))
        mp.setattr(service._baul, "register", AsyncMock())

        # Raw string that normalizes to DIFFERENT demographics than existing
        raw_input = RawPatientInput(
            raw_string="rex felino 5a María",
            source=PatientSource.LIS_FUJIFILM,
            received_at=datetime.now(timezone.utc),
        )

        result = await service.receive(raw_input, mock_async_session)

        assert result.created is False
        assert result.patient_id == 1

        # Merge guard: Fujifilm must NOT overwrite demographics
        assert existing_patient.species == "Canino"  # NOT "Felino" from normalizer
        assert existing_patient.sex == "Macho"  # NOT "Hembra" from normalizer
        assert existing_patient.owner_name == "Juan Pérez"  # NOT "María"
        # Age from normalizer is 5 años, but should NOT be overwritten
        assert existing_patient.age_value == 3  # Original value preserved
        assert existing_patient.age_display == "3 años"  # Original value preserved

        # The returned NormalizedPatient carries the normalized data,
        # but the actual DB record (existing_patient) is protected by the merge guard
        assert result.patient.species == "Desconocida"  # Fujifilm normalizer output
        assert result.patient.owner_name == "Sin Tutor"  # Fujifilm normalizer output


# ── _sanitize_patient_age tests ────────────────────────────────────────────────


class TestSanitizePatientAge:
    """Tests for the _sanitize_patient_age pure function."""

    def test_sanitize_age_consistent_true(self):
        """has_age=True, age_value=2 → unchanged (consistent data)."""
        result = _sanitize_patient_age(True, 2, "años", "2 años")
        assert result == (True, 2, "años", "2 años")

    def test_sanitize_age_consistent_false(self):
        """has_age=False, age_value=None → unchanged (consistent data)."""
        result = _sanitize_patient_age(False, None, None, None)
        assert result == (False, None, None, None)

    def test_sanitize_age_inconsistent_has_age_false_value_set(self):
        """has_age=False, age_value=2 → all become None/False (inconsistent DB data)."""
        result = _sanitize_patient_age(False, 2, "años", "2 años")
        assert result == (False, None, None, None)

    def test_sanitize_age_inconsistent_has_age_true_value_none(self):
        """has_age=True, age_value=None → all become None/False (inconsistent DB data)."""
        result = _sanitize_patient_age(True, None, "años", "2 años")
        assert result == (False, None, None, None)