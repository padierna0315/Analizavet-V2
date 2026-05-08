import pytest
import pytest_asyncio
from datetime import datetime, timezone
from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.domains.patients.models import Patient
from app.shared.models.test_result import TestResult
from app.shared.models.lab_value import LabValue
from app.shared.models.patient_image import PatientImage
from app.domains.patients.patient_registry import PatientRegistry


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as s:
        yield s
    await engine.dispose()


def make_patient_db() -> Patient:
    return Patient(
        name="Kitty",
        species="Felino",
        sex="Hembra",
        owner_name="Laura Cepeda",
        has_age=True,
        age_value=2,
        age_unit="años",
        age_display="2 años",
        source="LIS_OZELLE",
        normalized_name="kitty",
        normalized_owner="laura cepeda",
    )


@pytest.mark.asyncio
async def test_create_test_result(session):
    patient = make_patient_db()
    session.add(patient)
    await session.commit()
    await session.refresh(patient)

    result = TestResult(
        patient_id=patient.id,
        test_type="Hemograma",
        test_type_code="CBC",
        source="LIS_OZELLE",
        status="pendiente",
        received_at=datetime.now(timezone.utc),
    )
    session.add(result)
    await session.commit()
    await session.refresh(result)

    assert result.id is not None
    assert result.patient_id == patient.id
    assert result.flag_alto_count == 0
    assert result.status == "pendiente"


@pytest.mark.asyncio
async def test_create_lab_value(session):
    patient = make_patient_db()
    session.add(patient)
    await session.commit()
    await session.refresh(patient)

    test_result = TestResult(
        patient_id=patient.id,
        test_type="Hemograma",
        test_type_code="CBC",
        source="LIS_OZELLE",
        status="pendiente",
        received_at=datetime.now(timezone.utc),
    )
    session.add(test_result)
    await session.commit()
    await session.refresh(test_result)

    lab_value = LabValue(
        test_result_id=test_result.id,
        parameter_code="WBC",
        parameter_name_es="Leucocitos",
        raw_value="14.26",
        numeric_value=14.26,
        unit="10*9/L",
        reference_range="5.05-16.76",
        flag="NORMAL",
        machine_flag="N",
    )
    session.add(lab_value)
    await session.commit()
    await session.refresh(lab_value)

    assert lab_value.id is not None
    assert lab_value.flag == "NORMAL"
    assert lab_value.parameter_name_es == "Leucocitos"


@pytest.mark.asyncio
async def test_create_patient_image(session):
    patient = make_patient_db()
    session.add(patient)
    await session.commit()
    await session.refresh(patient)

    test_result = TestResult(
        patient_id=patient.id,
        test_type="Hemograma",
        test_type_code="CBC",
        source="LIS_OZELLE",
        status="pendiente",
        received_at=datetime.now(timezone.utc),
    )
    session.add(test_result)
    await session.commit()
    await session.refresh(test_result)

    image = PatientImage(
        test_result_id=test_result.id,
        parameter_code="WBC",
        parameter_name_es="Leucocitos",
        file_path="images/Kitty_LauraCepeda/20260424/Leucocitos.png",
        patient_folder="images/Kitty_LauraCepeda/20260424/",
    )
    session.add(image)
    await session.commit()
    await session.refresh(image)

    assert image.id is not None
    assert image.parameter_name_es == "Leucocitos"
    assert "Leucocitos" in image.file_path


@pytest.mark.asyncio
async def test_patient_registry_reserved(session):
    """PatientRegistry table exists and accepts data (future Turno system)."""
    registry_entry = PatientRegistry(
        turno_id="G2",
        name="Luna",
        species="Canino",
        sex="Hembra",
        age_display="2 años",
        owner_name="María García",
        profile="renal/hepatico",
        doctor_name="Giovanni",
    )
    session.add(registry_entry)
    await session.commit()
    await session.refresh(registry_entry)

    assert registry_entry.id is not None
    assert registry_entry.turno_id == "G2"
    assert registry_entry.active is True


@pytest.mark.asyncio
async def test_flag_default_is_normal(session):
    """LabValue.flag defaults to NORMAL."""
    patient = make_patient_db()
    session.add(patient)
    await session.commit()
    await session.refresh(patient)

    tr = TestResult(
        patient_id=patient.id,
        test_type="Hemograma",
        test_type_code="CBC",
        source="LIS_OZELLE",
        status="pendiente",
        received_at=datetime.now(timezone.utc),
    )
    session.add(tr)
    await session.commit()
    await session.refresh(tr)

    lv = LabValue(
        test_result_id=tr.id,
        parameter_code="RBC",
        parameter_name_es="Eritrocitos",
        raw_value="7.2",
        numeric_value=7.2,
        unit="10*12/L",
        reference_range="5.65-8.87",
        flag="NORMAL",
    )
    session.add(lv)
    await session.commit()
    await session.refresh(lv)
    assert lv.flag == "NORMAL"
