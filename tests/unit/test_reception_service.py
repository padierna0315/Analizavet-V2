import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession
from app.domains.patients.models import Patient
from app.domains.reception.schemas import RawPatientInput, PatientSource, NormalizedPatient
from app.domains.reception.service import ReceptionService
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
    mock_session.execute = AsyncMock(return_value=mock_result)
    
    return mock_session


def setup_mock_session_execute(mock_session, return_value=None):
    """Helper to configure session.execute().scalar_one_or_none()"""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = return_value
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