import pytest
import pytest_asyncio
from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.domains.patients.models import Patient
from app.domains.reception.schemas import NormalizedPatient, PatientSource
from app.domains.reception.baul import BaulService


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


def make_patient(
    name="Kitty",
    species="Felino",
    sex="Hembra",
    owner="Laura Cepeda",
    has_age=True,
    age_value=2,
    age_unit="años",
    age_display="2 años",
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
        owner_name=owner,
        source=source,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_new_patient_is_created(session):
    service = BaulService()
    patient = make_patient()
    result = await service.register(patient, session)
    assert result.created is True
    assert result.patient_id is not None
    assert result.patient_id > 0

@pytest.mark.asyncio
async def test_duplicate_patient_not_created(session):
    service = BaulService()
    patient = make_patient()
    result1 = await service.register(patient, session)
    result2 = await service.register(patient, session)
    assert result1.created is True
    assert result2.created is False
    assert result1.patient_id == result2.patient_id   # same DB record

@pytest.mark.asyncio
async def test_accent_insensitive_deduplication(session):
    """'Pérez' and 'Perez' are the same owner."""
    service = BaulService()
    p1 = make_patient(owner="Laura Pérez")
    p2 = make_patient(owner="Laura Perez")   # no accent
    r1 = await service.register(p1, session)
    r2 = await service.register(p2, session)
    assert r1.patient_id == r2.patient_id
    assert r2.created is False

@pytest.mark.asyncio
async def test_case_insensitive_deduplication(session):
    """'KITTY' and 'kitty' are the same patient."""
    service = BaulService()
    p1 = make_patient(name="KITTY")
    p2 = make_patient(name="kitty")
    r1 = await service.register(p1, session)
    r2 = await service.register(p2, session)
    assert r1.patient_id == r2.patient_id

@pytest.mark.asyncio
async def test_different_species_are_different_patients(session):
    """Same name + owner but different species = different patients."""
    service = BaulService()
    p_canino = make_patient(name="Luna", species="Canino", sex="Hembra")
    p_felino = make_patient(name="Luna", species="Felino", sex="Hembra")
    r1 = await service.register(p_canino, session)
    r2 = await service.register(p_felino, session)
    assert r1.patient_id != r2.patient_id
    assert r1.created is True
    assert r2.created is True

@pytest.mark.asyncio
async def test_different_owners_are_different_patients(session):
    """Same name + species but different owner = different patients."""
    service = BaulService()
    p1 = make_patient(owner="Laura Cepeda")
    p2 = make_patient(owner="Maria Garcia")
    r1 = await service.register(p1, session)
    r2 = await service.register(p2, session)
    assert r1.patient_id != r2.patient_id

@pytest.mark.asyncio
async def test_coproscopic_patient_no_age(session):
    """Patient without age (coproscopic) is stored correctly."""
    service = BaulService()
    patient = make_patient(has_age=False, age_value=None, age_unit=None, age_display=None)
    result = await service.register(patient, session)
    assert result.created is True
    assert result.patient_id > 0

@pytest.mark.asyncio
async def test_baul_result_contains_patient_data(session):
    service = BaulService()
    patient = make_patient()
    result = await service.register(patient, session)
    assert result.patient.name == "Kitty"
    assert result.patient.species == "Felino"
    assert result.patient.owner_name == "Laura Cepeda"
