"""Tests for PatientIntakeService — session_code lookup, temporal isolation,
normalization + dedup, new patient creation, source append, age sanitization,
and LIS source skip behavior.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession
from app.domains.patients.models import Patient
from app.domains.reception.schemas import RawPatientInput, PatientSource
from app.domains.reception.intake_service import PatientIntakeService
from datetime import datetime, timezone, timedelta


class MockBaulResult:
    def __init__(self, patient_id, created, patient):
        self.patient_id = patient_id
        self.created = created
        self.patient = patient


@pytest.fixture
def mock_async_session():
    """Mocks AsyncSession with commit and refresh as AsyncMock."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.commit.return_value = None
    mock_session.refresh.return_value = None
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_result.scalars.return_value.first.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)
    return mock_session


# ── 5.1.1 session_code lookup — existing patient ──────────────────────────

@pytest.mark.asyncio
async def test_session_code_lookup_finds_existing_patient(mock_async_session):
    """When session_code matches an existing patient, return created=False
    with the existing patient's demographics.
    """
    service = PatientIntakeService()

    existing = Patient(
        id=42,
        name="Rex",
        species="Canino",
        sex="Macho",
        owner_name="Juan Pérez",
        has_age=True,
        age_value=3,
        age_unit="años",
        age_display="3 años",
        source=PatientSource.APPSHEET.value,
        session_code="X1",
        normalized_name="rex",
        normalized_owner="juan perez",
        sources_received=[PatientSource.APPSHEET.value],
    )
    existing.created_at = datetime(2026, 5, 1, tzinfo=timezone.utc)

    session_result = MagicMock()
    session_result.scalar_one_or_none.return_value = existing
    mock_async_session.execute = AsyncMock(return_value=session_result)

    raw_input = RawPatientInput(
        raw_string="Rex Canino 3a Juan Pérez",
        session_code="X1",
        source=PatientSource.LIS_OZELLE,
        received_at=datetime(2026, 5, 10, tzinfo=timezone.utc),
    )

    result = await service.receive(raw_input, mock_async_session)

    assert result.created is False
    assert result.patient_id == 42
    assert result.patient.name == "Rex"
    assert result.patient.species == "Canino"
    assert PatientSource.LIS_OZELLE.value in existing.sources_received


# ── 5.1.2 temporal isolation — quarantine for old data ────────────────────

@pytest.mark.asyncio
async def test_temporal_isolation_triggers_quarantine(mock_async_session):
    """When received_at is before created_at minus tolerance, the input
    must NOT attach to the existing patient and a quarantine record is created.
    """
    service = PatientIntakeService()

    existing = Patient(
        id=7,
        name="Luna",
        species="Felino",
        sex="Hembra",
        owner_name="Ana",
        has_age=True,
        age_value=2,
        age_unit="años",
        age_display="2 años",
        source=PatientSource.MANUAL.value,
        session_code="OLD",
        normalized_name="luna",
        normalized_owner="ana",
        sources_received=[PatientSource.MANUAL.value],
    )
    # created_at far in the future relative to received
    existing.created_at = datetime(2026, 5, 20, tzinfo=timezone.utc)

    session_result = MagicMock()
    session_result.scalar_one_or_none.return_value = existing
    mock_async_session.execute = AsyncMock(return_value=session_result)

    # received_at is BEFORE the tolerance window → temporal mismatch
    raw_input = RawPatientInput(
        raw_string="Luna Felino 2a Ana",
        session_code="OLD",
        source=PatientSource.LIS_OZELLE,
        received_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )

    # After temporal rejection, it falls through to dedup → we need to mock _find_existing
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(service._baul, "_find_existing", AsyncMock(return_value=None))
        mp.setattr(service._baul, "register", AsyncMock(return_value=MockBaulResult(
            patient_id=99, created=True,
            patient=MagicMock(name="Luna"),
        )))

        result = await service.receive(raw_input, mock_async_session)

        # Must NOT reuse patient 7 — must create new one
        assert result.patient_id != 7
        assert result.created is True
        # Must have added a quarantine record
        assert mock_async_session.add.call_count >= 2  # quarantine + patient


# ── 5.1.3 normalization + dedup through _find_existing ────────────────────

@pytest.mark.asyncio
async def test_dedup_find_existing_returns_match(mock_async_session):
    """When no session_code matches, normalizer runs and _find_existing
    returns a match. Demographics from machine sources must NOT be overwritten.
    """
    service = PatientIntakeService()

    existing = Patient(
        id=10,
        name="Max",
        species="Canino",
        sex="Macho",
        owner_name="Pedro",
        has_age=True,
        age_value=5,
        age_unit="años",
        age_display="5 años",
        source=PatientSource.APPSHEET.value,
        normalized_name="max",
        normalized_owner="pedro",
        sources_received=[PatientSource.APPSHEET.value],
    )

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(service._baul, "_find_existing", AsyncMock(return_value=existing))
        mp.setattr(service._baul, "register", AsyncMock())

        raw_input = RawPatientInput(
            raw_string="max canino 5a pedro",
            source=PatientSource.LIS_OZELLE,
            received_at=datetime.now(timezone.utc),
        )

        result = await service.receive(raw_input, mock_async_session)

        assert result.created is False
        assert result.patient_id == 10
        # Machine source must NOT overwrite demographics
        assert existing.species == "Canino"
        assert existing.owner_name == "Pedro"
        assert PatientSource.LIS_OZELLE.value in existing.sources_received
        service._baul._find_existing.assert_awaited_once()


# ── 5.1.4 new patient creation ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_new_patient_creates_record(mock_async_session):
    """When no patient matches (session_code or dedup), a new patient
    is created via _baul.register.
    """
    service = PatientIntakeService()

    new_patient = Patient(
        id=99,
        name="Firulais",
        species="Canino",
        sex="Macho",
        owner_name="Juan",
        has_age=True,
        age_value=3,
        age_unit="años",
        age_display="3 años",
        source=PatientSource.LIS_OZELLE.value,
        normalized_name="firulais",
        normalized_owner="juan",
        sources_received=[],
    )
    mock_async_session.get.return_value = new_patient

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(service._baul, "_find_existing", AsyncMock(return_value=None))
        mp.setattr(
            service._baul, "register",
            AsyncMock(return_value=MockBaulResult(
                patient_id=99, created=True, patient=new_patient,
            )),
        )

        raw_input = RawPatientInput(
            raw_string="firulais canino 3a juan",
            source=PatientSource.LIS_OZELLE,
            received_at=datetime.now(timezone.utc),
        )

        result = await service.receive(raw_input, mock_async_session)

        assert result.created is True
        assert result.patient_id == 99
        assert result.patient.name == "Firulais"
        service._baul.register.assert_awaited_once()
        assert PatientSource.LIS_OZELLE.value in new_patient.sources_received


# ── 5.1.5 source append (no duplicate) ────────────────────────────────────

@pytest.mark.asyncio
async def test_source_append_no_duplicate(mock_async_session):
    """Receiving from the same source twice must not duplicate
    sources_received entries.
    """
    service = PatientIntakeService()

    existing = Patient(
        id=12,
        name="Coco",
        species="Canino",
        sex="Macho",
        owner_name="Juan",
        has_age=True,
        age_value=4,
        age_unit="años",
        age_display="4 años",
        source=PatientSource.LIS_OZELLE.value,
        normalized_name="coco",
        normalized_owner="juan",
        sources_received=[PatientSource.LIS_OZELLE.value],
    )

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(service._baul, "_find_existing", AsyncMock(return_value=existing))
        mp.setattr(service._baul, "register", AsyncMock())

        raw_input = RawPatientInput(
            raw_string="coco canino 4a juan",
            source=PatientSource.LIS_OZELLE,
            received_at=datetime.now(timezone.utc),
        )

        result = await service.receive(raw_input, mock_async_session)

        assert result.created is False
        assert result.patient_id == 12
        sources = existing.sources_received
        assert sources.count(PatientSource.LIS_OZELLE.value) == 1
        assert len(sources) == 1


# ── 5.1.6 age sanitization ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_age_sanitization_heals_inconsistent_db(mock_async_session):
    """When DB has inconsistent age fields (has_age=False but age_value=2),
    the sanitizer must heal them during session_code lookup path.
    """
    service = PatientIntakeService()

    # Existing patient with inconsistent age data: has_age=False but value set
    existing = Patient(
        id=33,
        name="Rocky",
        species="Canino",
        sex="Macho",
        owner_name="Carlos",
        has_age=False,  # inconsistent
        age_value=2,    # inconsistent
        age_unit="años",
        age_display="2 años",
        source=PatientSource.APPSHEET.value,
        session_code="R1",
        normalized_name="rocky",
        normalized_owner="carlos",
        sources_received=[PatientSource.APPSHEET.value],
    )
    existing.created_at = datetime(2026, 5, 1, tzinfo=timezone.utc)

    session_result = MagicMock()
    session_result.scalar_one_or_none.return_value = existing
    mock_async_session.execute = AsyncMock(return_value=session_result)

    raw_input = RawPatientInput(
        raw_string="Rocky Canino 2a Carlos",
        session_code="R1",
        source=PatientSource.LIS_FILE,
        received_at=datetime(2026, 5, 10, tzinfo=timezone.utc),
    )

    result = await service.receive(raw_input, mock_async_session)

    assert result.created is False
    assert result.patient_id == 33
    # After sanitization: has_age must be False, age_value must be None
    assert existing.has_age is False
    assert existing.age_value is None
    assert existing.age_unit is None
    assert existing.age_display is None
    # Returned NormalizedPatient must reflect sanitized state
    assert result.patient.has_age is False
    assert result.patient.age_value is None


# ── 5.1.7 LIS source skip — machine sources must not overwrite demographics ─

@pytest.mark.asyncio
async def test_lis_source_preserves_demographics(mock_async_session):
    """When dedup matches an existing patient and source is LIS_OZELLE,
    demographic fields (name, species, sex, owner_name, age) must NOT be
    overwritten.
    """
    service = PatientIntakeService()

    existing = Patient(
        id=44,
        name="Kiara",
        species="Felino",
        sex="Hembra",
        owner_name="María",
        has_age=True,
        age_value=7,
        age_unit="años",
        age_display="7 años",
        source=PatientSource.APPSHEET.value,
        normalized_name="kiara",
        normalized_owner="maria",
        sources_received=[PatientSource.APPSHEET.value],
    )

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(service._baul, "_find_existing", AsyncMock(return_value=existing))
        mp.setattr(service._baul, "register", AsyncMock())

        # Raw string normalizes to DIFFERENT demographics
        raw_input = RawPatientInput(
            raw_string="kiara canino 5a pedro",
            source=PatientSource.LIS_OZELLE,
            received_at=datetime.now(timezone.utc),
        )

        result = await service.receive(raw_input, mock_async_session)

        assert result.created is False
        assert result.patient_id == 44
        # LIS source: demographics must NOT be overwritten
        assert existing.name == "Kiara"
        assert existing.species == "Felino"  # NOT Canino
        assert existing.owner_name == "María"  # NOT Pedro
        assert existing.age_value == 7  # NOT 5
        # Source must still be appended
        assert PatientSource.LIS_OZELLE.value in existing.sources_received


# ── 5.1.8 LIS_FILE also skips demographic overwrite ───────────────────────

@pytest.mark.asyncio
async def test_lis_file_preserves_demographics(mock_async_session):
    """LIS_FILE source must also skip demographic overwrite on dedup match."""
    service = PatientIntakeService()

    existing = Patient(
        id=55,
        name="Buddy",
        species="Canino",
        sex="Macho",
        owner_name="Luis",
        has_age=True,
        age_value=8,
        age_unit="años",
        age_display="8 años",
        source=PatientSource.APPSHEET.value,
        normalized_name="buddy",
        normalized_owner="luis",
        sources_received=[PatientSource.APPSHEET.value],
    )

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(service._baul, "_find_existing", AsyncMock(return_value=existing))
        mp.setattr(service._baul, "register", AsyncMock())

        raw_input = RawPatientInput(
            raw_string="buddy felino 2a ana",
            source=PatientSource.LIS_FILE,
            received_at=datetime.now(timezone.utc),
        )

        result = await service.receive(raw_input, mock_async_session)

        assert result.created is False
        assert result.patient_id == 55
        assert existing.species == "Canino"  # NOT Felino
        assert existing.owner_name == "Luis"  # NOT Ana
        assert existing.age_value == 8  # NOT 2


# ── 5.1.9 MANUAL source DOES update demographics ──────────────────────────

@pytest.mark.asyncio
async def test_manual_source_updates_demographics(mock_async_session):
    """MANUAL (non-machine) source must update demographics on dedup match."""
    service = PatientIntakeService()

    existing = Patient(
        id=66,
        name="OldName",
        species="Canino",
        sex="Macho",
        owner_name="OldOwner",
        has_age=True,
        age_value=3,
        age_unit="años",
        age_display="3 años",
        source=PatientSource.APPSHEET.value,
        normalized_name="oldname",
        normalized_owner="oldowner",
        sources_received=[PatientSource.APPSHEET.value],
    )

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(service._baul, "_find_existing", AsyncMock(return_value=existing))
        mp.setattr(service._baul, "register", AsyncMock())

        raw_input = RawPatientInput(
            raw_string="nuevo felino 5a nuevaowner",
            source=PatientSource.MANUAL,
            received_at=datetime.now(timezone.utc),
        )

        result = await service.receive(raw_input, mock_async_session)

        assert result.created is False
        assert result.patient_id == 66
        # MANUAL source: demographics SHOULD be updated
        assert existing.name == "Nuevo"  # Updated
        assert existing.species == "Felino"  # Updated
        assert existing.owner_name == "Nuevaowner"  # Updated
        assert existing.age_value == 5  # Updated
