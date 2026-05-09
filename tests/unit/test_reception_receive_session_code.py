import pytest
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, delete
from app.domains.reception.service import ReceptionService
from app.domains.patients.models import Patient
from app.domains.reception.schemas import RawPatientInput, PatientSource

@pytest.mark.asyncio
async def test_receive_merges_by_session_code(session: AsyncSession):
    # Clear patients table
    await session.execute(delete(Patient))
    await session.commit()
    
    # 1. Pre-create patient with session_code (e.g. from AppSheet)
    p = Patient(
        name="Lucas",
        species="Felino",
        sex="Macho",
        owner_name="Luz Bonolis Serna",
        source=PatientSource.APPSHEET.value,
        session_code="A1",
        sources_received=[PatientSource.APPSHEET.value],
        normalized_name="lucas",
        normalized_owner="luz bonolis serna",
        has_age=True,
        age_value=13,
        age_unit="años",
        age_display="13 años"
    )
    session.add(p)
    await session.commit()
    
    service = ReceptionService()
    
    # 2. Machine sends "A1" as the session code and some raw string
    # Law 2: Write test for NEW behavior (merging by session_code)
    raw_input = RawPatientInput(
        raw_string="Lucas (Machine)",
        session_code="A1",
        source=PatientSource.LIS_OZELLE,
        received_at=datetime.now(timezone.utc)
    )
    
    result = await service.receive(raw_input, session)
    
    assert result.created is False
    assert result.patient_id == p.id
    
    # Verify sources_received was updated
    await session.refresh(p)
    assert PatientSource.LIS_OZELLE.value in p.sources_received
    assert PatientSource.APPSHEET.value in p.sources_received
