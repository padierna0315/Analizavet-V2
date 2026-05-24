import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession
from app.domains.patients.models import Patient
from app.domains.reception.schemas import RawPatientInput, PatientSource, NormalizedPatient
from app.domains.reception.service import ReceptionService
from app.domains.reception.helpers import _sanitize_patient_age
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
        mp.setattr(service._intake._baul, '_find_existing', AsyncMock(return_value=None))
        mp.setattr(service._intake._baul, 'register', AsyncMock(return_value=baul_register_return_value))


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
        mp.setattr(service._intake._baul, '_find_existing', AsyncMock(return_value=existing_patient))
        mp.setattr(service._intake._baul, 'register', AsyncMock())  # Should not be called
        
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
        mp.setattr(service._intake._baul, '_find_existing', AsyncMock(return_value=existing_patient))
        mp.setattr(service._intake._baul, 'register', AsyncMock())  # Should not be called
        
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
        mp.setattr(service._intake._baul, '_find_existing', AsyncMock(return_value=existing_patient))
        mp.setattr(service._intake._baul, 'register', AsyncMock())  # Should not be called
        
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
    """Ozelle data without session_code matches via dedup key (name+owner+species)."""
    service = ReceptionService()

    # Create an existing patient from AppSheet
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

    # Mock _find_existing (dedup) to return the existing patient
    mp = pytest.MonkeyPatch()
    mp.setattr(service._intake._baul, "_find_existing", AsyncMock(return_value=existing_patient))

    # Mock register (creation) — should NOT be called since dedup matches
    mp.setattr(service._intake._baul, "register", AsyncMock())

    try:
        raw_input = RawPatientInput(
            raw_string="rex canino 3a Juan Pérez",
            source=PatientSource.LIS_OZELLE,
            received_at=datetime.now(timezone.utc),
        )

        result = await service.receive(raw_input, mock_async_session)

        # Should NOT create a new patient — dedup found existing
        assert result.created is False
        assert result.patient_id == 1

        # Returned NormalizedPatient must have DB demographics
        assert result.patient.name == "Rex"
        assert result.patient.species == "Canino"
        assert result.patient.owner_name == "Juan Pérez"

        # sources_received should now include LIS_OZELLE
        assert PatientSource.LIS_OZELLE.value in existing_patient.sources_received
        assert PatientSource.APPSHEET.value in existing_patient.sources_received

        # _find_existing MUST have been called (name-only fallback removed)
        service._intake._baul._find_existing.assert_called_once()
        # register must NOT be called
        service._intake._baul.register.assert_not_called()
    finally:
        mp.undo()


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_ozelle_match_does_not_overwrite_demographics(mock_async_session):
    """Dedup match must preserve existing species/age/owner from DB, not overwrite."""
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

    # Mock _find_existing (dedup) to return the existing patient
    mp = pytest.MonkeyPatch()
    mp.setattr(service._intake._baul, "_find_existing", AsyncMock(return_value=existing_patient))
    mp.setattr(service._intake._baul, "register", AsyncMock())

    try:
        # Raw input normalizes to Canino/Pedro but dedup uses DB demographics
        raw_input = RawPatientInput(
            raw_string="luna canino 5a Pedro",
            source=PatientSource.LIS_FILE,
            received_at=datetime.now(timezone.utc),
        )

        result = await service.receive(raw_input, mock_async_session)

        # Patient demographics must remain intact (not overwritten by machine data)
        assert existing_patient.species == "Felino"  # NOT "Canino" (from normalizer)
        assert existing_patient.sex == "Hembra"
        assert existing_patient.owner_name == "María García"  # NOT "Pedro"
        assert existing_patient.has_age is True
        assert existing_patient.age_value == 5
        assert existing_patient.age_display == "5 años"

        # Returned NormalizedPatient carries normalized data (not DB data for machine sources)
        # The merge guard prevents DB overwrite, but result.patient shows what was parsed
        assert result.patient.name == "Luna"
        assert result.patient.owner_name == "Pedro"  # Normalized from raw_string

        # LIS_FILE source should have been added
        assert PatientSource.LIS_FILE.value in existing_patient.sources_received

        # _find_existing MUST have been called (no name-only shortcut)
        service._intake._baul._find_existing.assert_called_once()
        # register must NOT be called
        service._intake._baul.register.assert_not_called()
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

    # After fix: session_code is None → lookup skipped.
    # Only Ozelle name query runs → set up .all() returning [] (no match).
    ozelle_no_match = MagicMock()
    ozelle_no_match.scalars.return_value.all.return_value = []

    mock_async_session.execute = AsyncMock(side_effect=[ozelle_no_match])

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(service._intake._baul, "_find_existing", AsyncMock(return_value=existing_patient))
        mp.setattr(service._intake._baul, "register", AsyncMock())

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
        service._intake._baul._find_existing.assert_awaited_once()

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

    # After fix: session_code is None → lookup skipped.
    # Fujifilm name query → .all() returns [] (no name match) → falls through.
    fuji_no_match = MagicMock()
    fuji_no_match.scalars.return_value.all.return_value = []

    mock_async_session.execute = AsyncMock(side_effect=[fuji_no_match])

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(service._intake._baul, "_find_existing", AsyncMock(return_value=existing_patient))
        mp.setattr(service._intake._baul, "register", AsyncMock())

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


# ── Task 2.5: raw_string must NOT serve as session_code fallback ────────────


def _make_no_match_execute_result() -> MagicMock:
    """Return a mock execute result where nothing matches (both lookup styles)."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    result.scalars.return_value.first.return_value = None
    return result


@pytest.mark.asyncio
async def test_raw_string_not_used_as_session_code_fallback(mock_async_session):
    """When session_code is None, raw_string must NOT be used as session_code lookup.

    GIVEN a raw_string that looks like a session_code (e.g., "M5")
    WHEN session_code is None
    THEN the system skips session_code lookup entirely
    AND proceeds to dedup-based matching (name-only fallbacks removed).
    """
    service = ReceptionService()

    # Count how many times session.execute is called
    call_count = 0

    async def counting_execute(stmt):
        nonlocal call_count
        call_count += 1
        return _make_no_match_execute_result()

    mock_async_session.execute = AsyncMock(side_effect=counting_execute)

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(service._intake._baul, "_find_existing", AsyncMock(return_value=None))
        mock_register = AsyncMock(return_value=MockBaulResult(
            patient_id=99, created=True,
            patient=MagicMock(name="M5 Test Name"),
        ))
        mp.setattr(service._intake._baul, "register", mock_register)

        raw_input = RawPatientInput(
            raw_string="M5 Test Name Canino 3a Owner",
            session_code=None,  # No session code — must NOT fall back to raw_string
            source=PatientSource.LIS_OZELLE,
            received_at=datetime.now(timezone.utc),
        )

        result = await service.receive(raw_input, mock_async_session)

        # Must create a NEW patient — not match by raw_string "M5"
        assert result.created is True
        assert result.patient_id == 99

        # After fallback removal: execute called 0 times.
        # session_code lookup skipped (code is None).
        # Name-only fallback queries removed.
        assert call_count == 0, (
            f"Expected 0 execute calls (no session_code lookup, no name fallback), "
            f"got {call_count}. raw_string is being used as session_code fallback!"
        )


# ── Task 2.2: Fujifilm name fallback — 0, 1, 2+ matches ────────────────────


def _make_fujifilm_result(matches: list) -> MagicMock:
    """Return a mock execute result whose scalars().all() returns `matches`."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = matches
    return result


@pytest.mark.asyncio
async def test_fujifilm_name_match_zero_patients_creates_new(mock_async_session):
    """Fujifilm: 0 name matches → fallthrough to creation (created=True)."""
    service = ReceptionService()

    mock_async_session.execute = AsyncMock(
        side_effect=[_make_fujifilm_result([])]  # 0 matches by name
    )

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(service._intake._baul, "_find_existing", AsyncMock(return_value=None))
        mp.setattr(service._intake._baul, "register", AsyncMock(return_value=MockBaulResult(
            patient_id=50, created=True, patient=MagicMock(name="Fuji Zero"),
        )))

        raw_input = RawPatientInput(
            raw_string="Fuji Zero",
            source=PatientSource.LIS_FUJIFILM,
            received_at=datetime.now(timezone.utc),
        )

        result = await service.receive(raw_input, mock_async_session)

        assert result.created is True
        assert result.patient_id == 50


@pytest.mark.asyncio
async def test_fujifilm_name_match_one_patient_reuses(mock_async_session):
    """Fujifilm: dedup match via _find_existing reuses existing patient (name-only fallback removed)."""
    service = ReceptionService()

    existing = Patient(
        id=42,
        name="Kiara",
        species="Canino",
        sex="Hembra",
        owner_name="Owner",
        has_age=True,
        age_value=2,
        age_unit="años",
        age_display="2 años",
        source=PatientSource.LIS_FUJIFILM.value,
        normalized_name="kiara",
        normalized_owner="owner",
        sources_received=[PatientSource.LIS_FUJIFILM.value],
    )

    # No more fujifilm name-only query — go straight to _find_existing (dedup)
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(service._intake._baul, "_find_existing", AsyncMock(return_value=existing))
        mp.setattr(service._intake._baul, "register", AsyncMock())

        raw_input = RawPatientInput(
            raw_string="Kiara",
            source=PatientSource.LIS_FUJIFILM,
            received_at=datetime.now(timezone.utc),
        )

        result = await service.receive(raw_input, mock_async_session)

        assert result.created is False
        assert result.patient_id == 42
        assert result.patient.name == "Kiara"

        # _find_existing MUST be called (name-only fallback removed)
        service._intake._baul._find_existing.assert_awaited_once()


@pytest.mark.asyncio
async def test_fujifilm_name_match_two_plus_patients_creates_new(mock_async_session):
    """Fujifilm: 2+ name matches → create new patient (NO cross-contamination)."""
    service = ReceptionService()

    p1 = Patient(
        id=10, name="Kiara", species="Canino", sex="Hembra",
        owner_name="Owner A", has_age=True, age_value=3, age_unit="años",
        age_display="3 años", source=PatientSource.MANUAL.value,
        normalized_name="kiara", normalized_owner="owner a",
        sources_received=[PatientSource.MANUAL.value],
    )
    p2 = Patient(
        id=20, name="Kiara", species="Felino", sex="Macho",
        owner_name="Owner B", has_age=True, age_value=5, age_unit="años",
        age_display="5 años", source=PatientSource.APPSHEET.value,
        normalized_name="kiara", normalized_owner="owner b",
        sources_received=[PatientSource.APPSHEET.value],
    )

    # 2 matches — must NOT pick either (that would be cross-contamination)
    mock_async_session.execute = AsyncMock(
        side_effect=[_make_fujifilm_result([p1, p2])]
    )

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(service._intake._baul, "_find_existing", AsyncMock(return_value=None))
        mp.setattr(service._intake._baul, "register", AsyncMock(return_value=MockBaulResult(
            patient_id=99, created=True, patient=MagicMock(name="Kiara"),
        )))

        raw_input = RawPatientInput(
            raw_string="Kiara",
            source=PatientSource.LIS_FUJIFILM,
            received_at=datetime.now(timezone.utc),
        )

        result = await service.receive(raw_input, mock_async_session)

        # CRITICAL: 2+ matches → create NEW patient, NOT cross-contaminate
        assert result.created is True
        assert result.patient_id == 99

        # Must NOT use patient 10 or 20 (cross-contamination prevention)
        assert result.patient_id != 10
        assert result.patient_id != 20


# ── Task 2.3: Ozelle name fallback — 0, 1, 2+ matches ─────────────────────


def _make_ozelle_result(matches: list) -> MagicMock:
    """Return a mock execute result whose scalars().all() returns `matches`."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = matches
    return result


@pytest.mark.asyncio
async def test_ozelle_name_match_zero_patients_creates_new(mock_async_session):
    """Ozelle: 0 name matches → fallthrough → create new patient."""
    service = ReceptionService()

    mock_async_session.execute = AsyncMock(
        side_effect=[_make_ozelle_result([])]
    )

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(service._intake._baul, "_find_existing", AsyncMock(return_value=None))
        mp.setattr(service._intake._baul, "register", AsyncMock(return_value=MockBaulResult(
            patient_id=55, created=True, patient=MagicMock(name="Ozelle Zero"),
        )))

        raw_input = RawPatientInput(
            raw_string="Rex Canino 3a Owner",
            source=PatientSource.LIS_OZELLE,
            received_at=datetime.now(timezone.utc),
        )

        result = await service.receive(raw_input, mock_async_session)

        assert result.created is True
        assert result.patient_id == 55


@pytest.mark.asyncio
async def test_ozelle_name_match_one_patient_reuses(mock_async_session):
    """Ozelle: dedup match via _find_existing reuses existing patient (name-only fallback removed)."""
    service = ReceptionService()

    existing = Patient(
        id=77,
        name="Rocky",
        species="Canino",
        sex="Macho",
        owner_name="Carlos",
        has_age=True,
        age_value=4,
        age_unit="años",
        age_display="4 años",
        source=PatientSource.APPSHEET.value,
        normalized_name="rocky",
        normalized_owner="carlos",
        sources_received=[PatientSource.APPSHEET.value],
    )

    # No more Ozelle name-only query — go straight to _find_existing (dedup)
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(service._intake._baul, "_find_existing", AsyncMock(return_value=existing))
        mp.setattr(service._intake._baul, "register", AsyncMock())

        raw_input = RawPatientInput(
            raw_string="Rocky Canino 4a Carlos",
            source=PatientSource.LIS_OZELLE,
            received_at=datetime.now(timezone.utc),
        )

        result = await service.receive(raw_input, mock_async_session)

        assert result.created is False
        assert result.patient_id == 77
        assert result.patient.name == "Rocky"

        # _find_existing MUST be called (name-only fallback removed)
        service._intake._baul._find_existing.assert_awaited_once()


@pytest.mark.asyncio
async def test_ozelle_name_match_two_plus_patients_creates_new(mock_async_session):
    """Ozelle: 2+ name matches → create new patient (NO cross-contamination)."""
    service = ReceptionService()

    p1 = Patient(
        id=30, name="Luna", species="Canino", sex="Hembra",
        owner_name="Owner A", has_age=True, age_value=2, age_unit="años",
        age_display="2 años", source=PatientSource.MANUAL.value,
        normalized_name="luna", normalized_owner="owner a",
        sources_received=[PatientSource.MANUAL.value],
    )
    p2 = Patient(
        id=40, name="Luna", species="Felino", sex="Hembra",
        owner_name="Owner B", has_age=True, age_value=7, age_unit="años",
        age_display="7 años", source=PatientSource.APPSHEET.value,
        normalized_name="luna", normalized_owner="owner b",
        sources_received=[PatientSource.APPSHEET.value],
    )

    mock_async_session.execute = AsyncMock(
        side_effect=[_make_ozelle_result([p1, p2])]
    )

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(service._intake._baul, "_find_existing", AsyncMock(return_value=None))
        mp.setattr(service._intake._baul, "register", AsyncMock(return_value=MockBaulResult(
            patient_id=99, created=True, patient=MagicMock(name="Luna"),
        )))

        raw_input = RawPatientInput(
            raw_string="Luna Canino 2a Owner A",
            source=PatientSource.LIS_OZELLE,
            received_at=datetime.now(timezone.utc),
        )

        result = await service.receive(raw_input, mock_async_session)

        assert result.created is True
        assert result.patient_id == 99
        assert result.patient_id != 30
        assert result.patient_id != 40


# ── Task 3.1: Lazy linking — ProvenanceRecorder.link_to_patient calls ──────

FAKE_SESSION_CODE = "X9-20260501"
FAKE_PATIENT_ID = 42


@dataclass
class MockBaulResultWithId:
    patient_id: int
    created: bool
    patient: object


async def _receive_and_assert_linked(
    service: ReceptionService,
    mock_session: AsyncMock,
    source: PatientSource,
    raw_string: str = "Firulais Canino 3a Owner",
    session_code: str = FAKE_SESSION_CODE,
) -> None:
    """Helper: receive a patient and assert link_to_patient was called."""
    mp = pytest.MonkeyPatch().context()
    recorder_link_mock = AsyncMock()
    mp.setattr(
        "app.domains.reception.intake_service.ProvenanceRecorder",
        ProvenanceRecorderStub(link_mock=recorder_link_mock),
    )
    try:
        existing = Patient(
            id=FAKE_PATIENT_ID, name="Firulais", species="Canino", sex="Macho",
            owner_name="Owner", has_age=True, age_value=3, age_unit="años",
            age_display="3 años", source=source.value,
            normalized_name="firulais", normalized_owner="owner",
            sources_received=[source.value],
        )
        mp.setattr(service._intake._baul, "_find_existing", AsyncMock(return_value=existing))
        mp.setattr(service._intake._baul, "register", AsyncMock())

        raw_input = RawPatientInput(
            raw_string=raw_string,
            source=source,
            session_code=session_code,
            received_at=datetime.now(timezone.utc),
        )
        await service.receive(raw_input, mock_session)

        recorder_link_mock.assert_awaited_once_with(
            mock_session,
            session_code=session_code,
            patient_id=FAKE_PATIENT_ID,
            test_result_id=None,
        )
    finally:
        mp.undo()


class ProvenanceRecorderStub:
    """Stub that forwards record_sync/record_async but tracks link_to_patient."""

    def __init__(self, link_mock: AsyncMock | None = None):
        self.link_mock = link_mock or AsyncMock()

    async def link_to_patient(self, *args, **kwargs):
        await self.link_mock(*args, **kwargs)

    @staticmethod
    async def record_sync(*args, **kwargs):
        pass

    @staticmethod
    async def record_async(*args, **kwargs):
        return None


@pytest.mark.asyncio
async def test_link_to_patient_called_after_session_code_existing(mock_async_session):
    """When lookup by session_code finds an existing patient, link_to_patient is called."""
    service = ReceptionService()

    existing = Patient(
        id=FAKE_PATIENT_ID, name="Firulais", species="Canino", sex="Macho",
        owner_name="Owner", has_age=True, age_value=3, age_unit="años",
        age_display="3 años", source=PatientSource.APPSHEET.value,
        normalized_name="firulais", normalized_owner="owner",
        session_code=FAKE_SESSION_CODE,
        sources_received=[PatientSource.APPSHEET.value],
    )

    session_result = MagicMock()
    session_result.scalar_one_or_none.return_value = existing
    mock_async_session.execute = AsyncMock(return_value=session_result)

    mp = pytest.MonkeyPatch()
    recorder_link_mock = AsyncMock()
    stub = ProvenanceRecorderStub(link_mock=recorder_link_mock)
    mp.setattr(
        "app.domains.reception.intake_service.ProvenanceRecorder.link_to_patient",
        stub.link_to_patient,
    )
    try:
        raw_input = RawPatientInput(
            raw_string="Firulais Canino 3a Owner",
            source=PatientSource.LIS_OZELLE,
            session_code=FAKE_SESSION_CODE,
            received_at=datetime.now(timezone.utc),
        )
        await service.receive(raw_input, mock_async_session)

        recorder_link_mock.assert_awaited_once_with(
            session=mock_async_session,
            session_code=FAKE_SESSION_CODE,
            patient_id=FAKE_PATIENT_ID,
        )
    finally:
        mp.undo()


@pytest.mark.asyncio
async def test_link_to_patient_called_after_existing_patient_merge(mock_async_session):
    """When _find_existing returns a match, link_to_patient is called."""
    service = ReceptionService()

    existing = Patient(
        id=FAKE_PATIENT_ID, name="Firulais", species="Canino", sex="Macho",
        owner_name="Owner", has_age=True, age_value=3, age_unit="años",
        age_display="3 años", source=PatientSource.APPSHEET.value,
        normalized_name="firulais", normalized_owner="owner",
        sources_received=[PatientSource.APPSHEET.value],
    )

    mp = pytest.MonkeyPatch()
    mp.setattr(service._intake._baul, "_find_existing", AsyncMock(return_value=existing))
    mp.setattr(service._intake._baul, "register", AsyncMock())
    recorder_link_mock = AsyncMock()
    stub = ProvenanceRecorderStub(link_mock=recorder_link_mock)
    mp.setattr(
        "app.domains.reception.intake_service.ProvenanceRecorder.link_to_patient",
        stub.link_to_patient,
    )
    try:
        raw_input = RawPatientInput(
            raw_string="Firulais Canino 3a Owner",
            source=PatientSource.MANUAL,
            session_code=FAKE_SESSION_CODE,
            received_at=datetime.now(timezone.utc),
        )
        await service.receive(raw_input, mock_async_session)

        recorder_link_mock.assert_awaited_once_with(
            session=mock_async_session,
            session_code=FAKE_SESSION_CODE,
            patient_id=FAKE_PATIENT_ID,
        )
    finally:
        mp.undo()


@pytest.mark.asyncio
async def test_link_to_patient_called_after_new_patient_created(mock_async_session):
    """When a new patient is created via _baul.register, link_to_patient is called."""
    service = ReceptionService()

    new_patient = Patient(
        id=FAKE_PATIENT_ID, name="NewPatient", species="Canino", sex="Macho",
        owner_name="Owner", has_age=True, age_value=3, age_unit="años",
        age_display="3 años", source=PatientSource.MANUAL.value,
        normalized_name="newpatient", normalized_owner="owner",
        sources_received=[],
    )
    mock_async_session.get.return_value = new_patient

    mp = pytest.MonkeyPatch()
    mp.setattr(service._intake._baul, "_find_existing", AsyncMock(return_value=None))
    mp.setattr(
        service._intake._baul, "register",
        AsyncMock(return_value=MockBaulResult(
            patient_id=FAKE_PATIENT_ID, created=True, patient=new_patient,
        )),
    )
    recorder_link_mock = AsyncMock()
    stub = ProvenanceRecorderStub(link_mock=recorder_link_mock)
    mp.setattr(
        "app.domains.reception.intake_service.ProvenanceRecorder.link_to_patient",
        stub.link_to_patient,
    )
    try:
        raw_input = RawPatientInput(
            raw_string="NewPatient Canino 3a Owner",
            source=PatientSource.MANUAL,
            session_code=FAKE_SESSION_CODE,
            received_at=datetime.now(timezone.utc),
        )
        await service.receive(raw_input, mock_async_session)

        recorder_link_mock.assert_awaited_once_with(
            session=mock_async_session,
            session_code=FAKE_SESSION_CODE,
            patient_id=FAKE_PATIENT_ID,
        )
    finally:
        mp.undo()


# ── Task 2.4: File source name fallback ────────────────────────────────────


@pytest.mark.asyncio
async def test_file_name_match_zero_patients_creates_new(mock_async_session):
    """File source: 0 name matches → create new patient."""
    service = ReceptionService()

    mock_async_session.execute = AsyncMock(
        side_effect=[_make_ozelle_result([])]
    )

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(service._intake._baul, "_find_existing", AsyncMock(return_value=None))
        mp.setattr(service._intake._baul, "register", AsyncMock(return_value=MockBaulResult(
            patient_id=88, created=True, patient=MagicMock(name="File Zero"),
        )))

        raw_input = RawPatientInput(
            raw_string="Max Canino 3a Pedro",
            source=PatientSource.LIS_FILE,
            received_at=datetime.now(timezone.utc),
        )

        result = await service.receive(raw_input, mock_async_session)

        assert result.created is True
        assert result.patient_id == 88


@pytest.mark.asyncio
async def test_file_name_match_one_patient_reuses(mock_async_session):
    """File source: dedup match via _find_existing reuses existing patient (name-only fallback removed)."""
    service = ReceptionService()

    existing = Patient(
        id=66,
        name="Max",
        species="Canino",
        sex="Macho",
        owner_name="Pedro",
        has_age=True,
        age_value=6,
        age_unit="años",
        age_display="6 años",
        source=PatientSource.APPSHEET.value,
        normalized_name="max",
        normalized_owner="pedro",
        sources_received=[PatientSource.APPSHEET.value],
    )

    # No more File name-only query — go straight to _find_existing (dedup)
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(service._intake._baul, "_find_existing", AsyncMock(return_value=existing))
        mp.setattr(service._intake._baul, "register", AsyncMock())

        raw_input = RawPatientInput(
            raw_string="Max Canino 6a Pedro",
            source=PatientSource.LIS_FILE,
            received_at=datetime.now(timezone.utc),
        )

        result = await service.receive(raw_input, mock_async_session)

        assert result.created is False
        assert result.patient_id == 66
        assert result.patient.name == "Max"

        # _find_existing MUST be called (name-only fallback removed)
        service._intake._baul._find_existing.assert_awaited_once()


@pytest.mark.asyncio
async def test_file_name_match_two_plus_patients_creates_new(mock_async_session):
    """File source: 2+ name matches → create new (NO cross-contamination)."""
    service = ReceptionService()

    p1 = Patient(
        id=12, name="Coco", species="Canino", sex="Macho",
        owner_name="Owner X", has_age=True, age_value=1, age_unit="años",
        age_display="1 año", source=PatientSource.MANUAL.value,
        normalized_name="coco", normalized_owner="owner x",
        sources_received=[PatientSource.MANUAL.value],
    )
    p2 = Patient(
        id=13, name="Coco", species="Canino", sex="Hembra",
        owner_name="Owner Y", has_age=True, age_value=8, age_unit="años",
        age_display="8 años", source=PatientSource.APPSHEET.value,
        normalized_name="coco", normalized_owner="owner y",
        sources_received=[PatientSource.APPSHEET.value],
    )

    mock_async_session.execute = AsyncMock(
        side_effect=[_make_ozelle_result([p1, p2])]
    )

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(service._intake._baul, "_find_existing", AsyncMock(return_value=None))
        mp.setattr(service._intake._baul, "register", AsyncMock(return_value=MockBaulResult(
            patient_id=99, created=True, patient=MagicMock(name="Coco"),
        )))

        raw_input = RawPatientInput(
            raw_string="Coco Canino 1a Owner X",
            source=PatientSource.LIS_FILE,
            received_at=datetime.now(timezone.utc),
        )

        result = await service.receive(raw_input, mock_async_session)

        assert result.created is True
        assert result.patient_id == 99
        assert result.patient_id != 12
        assert result.patient_id != 13