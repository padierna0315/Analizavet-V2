import pytest
import pytest_asyncio
from datetime import datetime, timezone
from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.domains.patients.models import Patient
from app.shared.models.test_result import TestResult
from app.shared.models.lab_value import LabValue
from app.domains.taller.schemas import FlagBatchRequest, RawLabValueInput
from app.domains.taller.engine import TallerFlaggingEngine


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as s:
        yield s
    await engine.dispose()


async def create_test_result(session: AsyncSession) -> TestResult:
    """Helper: create a patient + test result in DB."""
    patient = Patient(
        name="Kitty", species="Felino", sex="Hembra",
        owner_name="Laura Cepeda", has_age=True,
        age_value=2, age_unit="años", age_display="2 años",
        source="LIS_OZELLE",
        normalized_name="kitty", normalized_owner="laura cepeda",
    )
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
    return tr


def make_raw_values() -> list[RawLabValueInput]:
    """Real-ish values from Ozelle log for a canine patient."""
    return [
        RawLabValueInput(
            parameter_code="WBC", parameter_name_es="Leucocitos",
            raw_value="14.26", numeric_value=14.26,
            unit="10*9/L", reference_range="5.05-16.76", machine_flag="N",
        ),
        RawLabValueInput(
            parameter_code="RBC", parameter_name_es="Eritrocitos",
            raw_value="7.2", numeric_value=7.2,
            unit="10*12/L", reference_range="5.65-8.87", machine_flag="N",
        ),
        RawLabValueInput(
            parameter_code="HGB", parameter_name_es="Hemoglobina",
            raw_value="5.0", numeric_value=5.0,
            unit="g/dL", reference_range="13.1-20.5", machine_flag="L",
        ),
    ]


@pytest.mark.asyncio
async def test_flag_test_result_saves_lab_values(session):
    tr = await create_test_result(session)
    engine = TallerFlaggingEngine()

    request = FlagBatchRequest(
        test_result_id=tr.id,
        species="Felino",
        values=make_raw_values(),
    )
    result = await engine.flag_test_result(request, session)

    assert result.status == "listo"
    assert result.test_result_id == tr.id
    assert len(result.flagged_values) == 3


@pytest.mark.asyncio
async def test_flag_updates_test_result_status(session):
    tr = await create_test_result(session)
    engine = TallerFlaggingEngine()

    request = FlagBatchRequest(
        test_result_id=tr.id,
        species="Felino",
        values=make_raw_values(),
    )
    await engine.flag_test_result(request, session)

    # Refresh and check
    await session.refresh(tr)
    assert tr.status == "listo"
    assert tr.processed_at is not None


@pytest.mark.asyncio
async def test_flag_summary_counts(session):
    tr = await create_test_result(session)
    engine = TallerFlaggingEngine()

    request = FlagBatchRequest(
        test_result_id=tr.id,
        species="Felino",
        values=make_raw_values(),
    )
    result = await engine.flag_test_result(request, session)

    # Summary must have all three keys
    assert "ALTO" in result.summary
    assert "NORMAL" in result.summary
    assert "BAJO" in result.summary
    total = sum(result.summary.values())
    assert total == 3


@pytest.mark.asyncio
async def test_flag_lab_values_stored_in_db(session):
    from sqlmodel import select
    tr = await create_test_result(session)
    engine = TallerFlaggingEngine()

    request = FlagBatchRequest(
        test_result_id=tr.id,
        species="Felino",
        values=make_raw_values(),
    )
    await engine.flag_test_result(request, session)

    result = await session.execute(
        select(LabValue).where(LabValue.test_result_id == tr.id)
    )
    lab_values = result.scalars().all()
    assert len(lab_values) == 3
    codes = {lv.parameter_code for lv in lab_values}
    assert "WBC" in codes
    assert "RBC" in codes
    assert "HGB" in codes


@pytest.mark.asyncio
async def test_flag_invalid_test_result_raises(session):
    engine = TallerFlaggingEngine()
    request = FlagBatchRequest(
        test_result_id=99999,
        species="Felino",
        values=make_raw_values(),
    )
    with pytest.raises(ValueError, match="no encontrado"):
        await engine.flag_test_result(request, session)


@pytest.mark.asyncio
async def test_unknown_parameter_does_not_crash(session):
    """Unknown parameter → flag=NORMAL, engine continues."""
    tr = await create_test_result(session)
    engine = TallerFlaggingEngine()

    values = [RawLabValueInput(
        parameter_code="UNKNOWN_PARAM",
        parameter_name_es="Parámetro Desconocido",
        raw_value="99.9", numeric_value=99.9,
        unit="units", reference_range="0-100",
    )]
    request = FlagBatchRequest(
        test_result_id=tr.id, species="Felino", values=values
    )
    result = await engine.flag_test_result(request, session)
    assert result.status == "listo"
    assert result.flagged_values[0].flag == "NORMAL"

@pytest.mark.asyncio
async def test_flag_nsh_canine_high(session):
    """Verify NSH# for Canine is flagged as ALTO when value is high."""
    tr = await create_test_result(session)
    engine = TallerFlaggingEngine()

    # NSH# range for Canine: (0.00, 0.40)
    values = [RawLabValueInput(
        parameter_code="NSH#",
        parameter_name_es="Neutrófilos Hipersegmentados",
        raw_value="0.50", numeric_value=0.50,
        unit="x10^3/µL", reference_range="0.00-0.40",
    )]
    request = FlagBatchRequest(
        test_result_id=tr.id, species="Canino", values=values
    )
    result = await engine.flag_test_result(request, session)
    assert result.status == "listo"
    assert result.flagged_values[0].flag == "ALTO"
    assert result.flagged_values[0].reference_range == "0.0-0.4 x10^3/µL"

@pytest.mark.asyncio
async def test_flag_nsh_canine_normal(session):
    """Verify NSH# for Canine is flagged as NORMAL when value is in range."""
    tr = await create_test_result(session)
    engine = TallerFlaggingEngine()

    # NSH# range for Canine: (0.00, 0.40)
    values = [RawLabValueInput(
        parameter_code="NSH#",
        parameter_name_es="Neutrófilos Hipersegmentados",
        raw_value="0.20", numeric_value=0.20,
        unit="x10^3/µL", reference_range="0.00-0.40",
    )]
    request = FlagBatchRequest(
        test_result_id=tr.id, species="Canino", values=values
    )
    result = await engine.flag_test_result(request, session)
    assert result.status == "listo"
    assert result.flagged_values[0].flag == "NORMAL"
    assert result.flagged_values[0].reference_range == "0.0-0.4 x10^3/µL"
