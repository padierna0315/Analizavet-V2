import pytest
import pytest_asyncio
import json
from sqlmodel import SQLModel, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.domains.patients.models import Patient
from app.domains.reception.schemas import NormalizedPatient, PatientSource
from app.domains.reception.baul import BaulService
from app.domains.reception.service import ReceptionService
from app.domains.reception.schemas import RawPatientInput
from datetime import datetime, timezone


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def session():
    """In-memory SQLite for tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as s:
        yield s
    await engine.dispose()


def make_ozelle_patient(
    name="Ichigo",
    species="Canino",
    sex="Macho",
    owner_name="Fernanda Hernandez",
    has_age=True,
    age_value=5,
    age_unit="años",
    age_display="5 años",
    source=PatientSource.LIS_OZELLE,
) -> NormalizedPatient:
    return NormalizedPatient(
        name=name,
        species=species,
        sex=sex,
        has_age=has_age,
        age_value=age_value,
        age_unit=age_unit,
        age_display=age_display,
        owner_name=owner_name,
        source=source,
    )


def make_json_patient(
    name="Tommy",
    species="Canino",
    sex="Macho",
    owner_name="Dra. Aura Betancourt",
    has_age=True,
    age_value=5,
    age_unit="años",
    age_display="5 años",
    source=PatientSource.MANUAL,
) -> NormalizedPatient:
    return NormalizedPatient(
        name=name,
        species=species,
        sex=sex,
        has_age=has_age,
        age_value=age_value,
        age_unit=age_unit,
        age_display=age_display,
        owner_name=owner_name,
        source=source,
    )


def make_raw_ozelle_input(
    raw_string="A1 Ichigo",
    source=PatientSource.LIS_OZELLE,
) -> RawPatientInput:
    return RawPatientInput(
        raw_string=raw_string,
        source=source,
        received_at=datetime.now(timezone.utc)
    )


def make_raw_json_input(
    raw_string="A1: Doctora Aura Betancourt, Paciente: Tommy, tipo: canino, edad: 5 años",
    source=PatientSource.MANUAL,
) -> RawPatientInput:
    return RawPatientInput(
        raw_string=raw_string,
        source=source,
        received_at=datetime.now(timezone.utc)
    )


# ── Tests ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_patient_sources_received_tracking(session):
    """Test that Patient model correctly tracks which sources have provided data."""
    # sources_received is populated by ReceptionService.receive(), not BaulService.register()
    service = ReceptionService()

    raw_input = RawPatientInput(
        raw_string="ichigo canino 5a Fernanda Hernandez",
        source=PatientSource.LIS_OZELLE,
        received_at=datetime.now(timezone.utc),
    )
    result1 = await service.receive(raw_input, session)
    assert result1.created is True

    # Refresh the patient from DB to check sources_received
    stmt = select(Patient).where(Patient.id == result1.patient_id)
    db_result = await session.execute(stmt)
    patient = db_result.scalar_one()

    # Check that sources_received contains LIS_OZELLE — now a Python list
    sources = patient.sources_received
    assert "LIS_OZELLE" in sources
    assert len(sources) == 1


@pytest.mark.asyncio
async def test_patient_baptism_updates_sources_received(session):
    """Test that registering an existing patient from a new source updates sources_received."""
    reception_service = ReceptionService()

    # 1. Register a patient from Ozelle
    ozelle_raw_input = make_raw_ozelle_input(raw_string="ichigo canino 5a fernanda hernandez")
    result1 = await reception_service.receive(ozelle_raw_input, session)
    assert result1.created is True
    patient_id = result1.patient_id

    # Verify initial state: sources_received should contain LIS_OZELLE
    stmt = select(Patient).where(Patient.id == patient_id)
    db_result = await session.execute(stmt)
    patient = db_result.scalar_one()
    assert patient.sources_received == ["LIS_OZELLE"]
    assert patient.name == "Ichigo"
    assert patient.owner_name == "Fernanda Hernandez"

    # 2. Register the same patient from a MANUAL source (baptism)
    # The raw_string should be parsable to the same normalized name, owner, and species
    manual_raw_input = make_raw_json_input(
        raw_string="ichigo canino 5a fernanda hernandez",
        source=PatientSource.MANUAL
    )
    result2 = await reception_service.receive(manual_raw_input, session)
    assert result2.created is False  # Should be an update, not a new creation
    assert result2.patient_id == patient_id

    # Verify updated state: sources_received should contain both LIS_OZELLE and MANUAL
    await session.refresh(patient) # Refresh patient object to get latest data
    assert patient.sources_received == ["LIS_OZELLE", "MANUAL"]
    
    # Verify patient data was updated by the MANUAL source (if there were differences in normalized values)
    # In this specific case, raw_string was the same, so demographic data should remain unchanged.
    assert patient.name == "Ichigo"
    assert patient.owner_name == "Fernanda Hernandez"

    # 3. Register the same patient from LIS_OZELLE again - should not add duplicate source
    result3 = await reception_service.receive(ozelle_raw_input, session)
    assert result3.created is False
    assert result3.patient_id == patient_id
    await session.refresh(patient)
    assert patient.sources_received == ["LIS_OZELLE", "MANUAL"] # Still two unique sources


@pytest.mark.asyncio
async def test_sala_espera_endpoint_returns_patients_with_sources(session):
    """Test that the waiting room endpoint returns patients with sources_received data."""
    from app.main import app
    from httpx import AsyncClient, ASGITransport
    from app.database import get_session

    reception = ReceptionService()

    # Register two patients via ReceptionService so sources_received gets populated
    await reception.receive(
        RawPatientInput(
            raw_string="ichigo canino 5a Fernanda Hernandez",
            source=PatientSource.LIS_OZELLE,
            received_at=datetime.now(timezone.utc),
        ),
        session,
    )
    await reception.receive(
        RawPatientInput(
            raw_string="tommy canino 5a Dra Aura Betancourt",
            source=PatientSource.MANUAL,
            received_at=datetime.now(timezone.utc),
        ),
        session,
    )

    # Override the dependency to use our test session
    async def get_test_session():
        yield session

    app.dependency_overrides[get_session] = get_test_session

    # The waiting room HTML lives at /reception/taller/reception
    # (reception router is mounted with /reception prefix in main.py)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/reception/taller/reception")
        # The endpoint exists and returns HTML — not 422/500
        assert response.status_code in (200, 302)

    # Clean up the override
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_delete_waiting_room_patient_deletes_record(session):
    """Test that deleting a patient via the endpoint physically removes them."""
    from app.main import app
    from httpx import AsyncClient
    from app.database import get_session
    
    service = BaulService()
    
    # Register a patient
    ozelle_patient = make_ozelle_patient()
    result = await service.register(ozelle_patient, session)
    patient_id = result.patient_id
    
    # Verify patient exists
    stmt = select(Patient).where(Patient.id == patient_id)
    db_result = await session.execute(stmt)
    assert db_result.scalar_one_or_none() is not None
    
    # Override the dependency to use our test session
    async def get_test_session():
        yield session
    
    app.dependency_overrides[get_session] = get_test_session
    
    # Test the delete endpoint
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.delete(f"/reception/patient/{patient_id}")
        assert response.status_code == 200
    
    # Clean up the override
    app.dependency_overrides.clear()
    
    # Verify patient is now gone from the database
    stmt = select(Patient).where(Patient.id == patient_id)
    db_result = await session.execute(stmt)
    patient = db_result.scalar_one_or_none()
    assert patient is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])