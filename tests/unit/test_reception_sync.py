import pytest
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, delete
from app.domains.reception.service import ReceptionService
from app.services.appsheet import AppSheetPatient
from app.domains.patients.models import Patient
from app.domains.reception.schemas import PatientSource

@pytest.mark.asyncio
async def test_sync_from_appsheet_new_patient(session: AsyncSession):
    # Clear patients table first to avoid MultipleResultsFound
    await session.execute(delete(Patient))
    await session.commit()
    
    service = ReceptionService()
    
    appsheet_patients = [
        AppSheetPatient(
            Codigo_Corto="A1",
            Doctora="Aura",
            Categoria_Examen="Examen de sangre",
            Examen_Especifico="Perfil Básico (PQ1)",
            Nombre_Mascota="Lucas",
            Especie="Felino",
            Sexo="Macho",
            Edad_Numero="13",
            Edad_Unidad="Años",
            Nombre_Tutor="Luz Bonolis Serna",
            Raza="Mestizo"
        )
    ]
    
    await service.sync_from_appsheet(appsheet_patients, session)
    
    # Verify patient was created
    result = await session.execute(select(Patient).where(Patient.session_code == "A1"))
    patient = result.scalar_one_or_none()
    
    assert patient is not None
    assert patient.name == "Lucas"
    assert patient.owner_name == "Luz Bonolis Serna"
    assert patient.session_code == "A1"
    assert PatientSource.APPSHEET.value in patient.sources_received

@pytest.mark.asyncio
async def test_sync_from_appsheet_update_existing(session: AsyncSession):
    # Clear patients table first
    await session.execute(delete(Patient))
    await session.commit()

    # Pre-create a patient with same session_code but different source
    p = Patient(
        name="Lucas",
        species="Felino",
        sex="Macho",
        owner_name="Luz Bonolis Serna",
        source=PatientSource.LIS_OZELLE.value,
        session_code="A1",
        sources_received=[PatientSource.LIS_OZELLE.value],
        normalized_name="lucas",
        normalized_owner="luz bonolis serna"
    )
    session.add(p)
    await session.commit()
    
    service = ReceptionService()
    appsheet_patients = [
        AppSheetPatient(
            Codigo_Corto="A1",
            Doctora="Aura",
            Categoria_Examen="Examen de sangre",
            Examen_Especifico="Perfil Básico (PQ1)",
            Nombre_Mascota="Lucas",
            Especie="Felino",
            Sexo="Macho",
            Edad_Numero="13",
            Edad_Unidad="Años",
            Nombre_Tutor="Luz Bonolis Serna",
            Raza="Mestizo"
        )
    ]
    
    await service.sync_from_appsheet(appsheet_patients, session)
    
    # Verify patient was updated
    result = await session.execute(select(Patient).where(Patient.session_code == "A1"))
    patient = result.scalar_one_or_none()
    
    assert patient is not None
    assert PatientSource.APPSHEET.value in patient.sources_received
    assert PatientSource.LIS_OZELLE.value in patient.sources_received
    assert patient.breed == "Mestizo"

@pytest.mark.asyncio
async def test_sync_from_appsheet_multiple(session: AsyncSession):
    await session.execute(delete(Patient))
    await session.commit()

    service = ReceptionService()
    appsheet_patients = [
        AppSheetPatient(Codigo_Corto="A1", Doctora="A", Categoria_Examen="E", Examen_Especifico="S",
                        Nombre_Mascota="N1", Especie="Felino", Sexo="M", Edad_Numero="1", Edad_Unidad="A",
                        Nombre_Tutor="T1", Raza="R1"),
        AppSheetPatient(Codigo_Corto="A2", Doctora="B", Categoria_Examen="E", Examen_Especifico="S",
                        Nombre_Mascota="N2", Especie="Canino", Sexo="H", Edad_Numero="2", Edad_Unidad="A",
                        Nombre_Tutor="T2", Raza="R2")
    ]
    
    count = await service.sync_from_appsheet(appsheet_patients, session)
    assert count == 2
    
    result = await session.execute(select(Patient).order_by(Patient.session_code))
    patients = result.scalars().all()
    assert len(patients) == 2
    assert patients[0].session_code == "A1"
    assert patients[1].session_code == "A2"
