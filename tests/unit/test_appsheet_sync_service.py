import pytest
from sqlmodel import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.appsheet import AppSheetPatient
from app.domains.patients.models import Patient
from app.domains.exam_order.models import ExamOrder
from app.domains.reception.schemas import PatientSource

# RED: AppSheetSyncService does not exist yet → ImportError
from app.domains.reception.appsheet_service import AppSheetSyncService


@pytest.mark.asyncio
async def test_sync_from_appsheet_new_patient(session: AsyncSession):
    """sync_from_appsheet creates a new patient and ExamOrder from AppSheet data."""
    await session.execute(delete(ExamOrder))
    await session.execute(delete(Patient))
    await session.commit()

    sync_svc = AppSheetSyncService()

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
            Raza="Mestizo",
        )
    ]

    count = await sync_svc.sync_from_appsheet(appsheet_patients, session)
    assert count == 1

    result = await session.execute(
        select(Patient).where(Patient.session_code == "A1")
    )
    patient = result.scalar_one_or_none()
    assert patient is not None
    assert patient.name == "Lucas"
    assert patient.owner_name == "Luz Bonolis Serna"
    assert patient.session_code == "A1"
    assert patient.doctor_name == "Aura"
    assert patient.appsheet_test_type == "Química Sanguínea"
    assert patient.appsheet_test_type_code == "CHEM"
    assert PatientSource.APPSHEET.value in patient.sources_received

    # Verify ExamOrder was created
    order_result = await session.execute(
        select(ExamOrder).where(ExamOrder.session_code == "A1")
    )
    order = order_result.scalar_one_or_none()
    assert order is not None
    assert order.patient_id == patient.id
    assert order.status == "pending"
    assert len(order.exam_types) > 0


@pytest.mark.asyncio
async def test_sync_from_appsheet_update_existing(session: AsyncSession):
    """sync_from_appsheet updates an existing patient by session_code."""
    await session.execute(delete(ExamOrder))
    await session.execute(delete(Patient))
    await session.commit()

    # Pre-create patient with same session_code but different source
    p = Patient(
        name="Lucas",
        species="Felino",
        sex="Macho",
        owner_name="Luz Bonolis Serna",
        source=PatientSource.LIS_OZELLE.value,
        session_code="A1",
        sources_received=[PatientSource.LIS_OZELLE.value],
        normalized_name="lucas",
        normalized_owner="luz bonolis serna",
    )
    session.add(p)
    await session.commit()

    sync_svc = AppSheetSyncService()

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
            Raza="Mestizo",
        )
    ]

    await sync_svc.sync_from_appsheet(appsheet_patients, session)

    result = await session.execute(
        select(Patient).where(Patient.session_code == "A1")
    )
    patient = result.scalar_one_or_none()
    assert patient is not None
    assert patient.doctor_name == "Aura"
    assert patient.appsheet_test_type == "Química Sanguínea"
    assert PatientSource.APPSHEET.value in patient.sources_received
    assert PatientSource.LIS_OZELLE.value in patient.sources_received
    assert patient.breed == "Mestizo"

    # Verify ExamOrder was created
    order_result = await session.execute(
        select(ExamOrder).where(ExamOrder.session_code == "A1")
    )
    order = order_result.scalar_one_or_none()
    assert order is not None
    assert order.patient_id == patient.id


@pytest.mark.asyncio
async def test_sync_from_appsheet_multiple(session: AsyncSession):
    """sync_from_appsheet with multiple patients returns correct count."""
    await session.execute(delete(ExamOrder))
    await session.execute(delete(Patient))
    await session.commit()

    sync_svc = AppSheetSyncService()
    patients = [
        AppSheetPatient(
            Codigo_Corto="A1", Doctora="A", Categoria_Examen="E",
            Examen_Especifico="S", Nombre_Mascota="N1", Especie="Felino",
            Sexo="M", Edad_Numero="1", Edad_Unidad="A",
            Nombre_Tutor="T1", Raza="R1",
        ),
        AppSheetPatient(
            Codigo_Corto="A2", Doctora="B", Categoria_Examen="E",
            Examen_Especifico="S", Nombre_Mascota="N2", Especie="Canino",
            Sexo="H", Edad_Numero="2", Edad_Unidad="A",
            Nombre_Tutor="T2", Raza="R2",
        ),
    ]

    count = await sync_svc.sync_from_appsheet(patients, session)
    assert count == 2

    result = await session.execute(
        select(Patient).order_by(Patient.session_code)
    )
    db_patients = result.scalars().all()
    assert len(db_patients) == 2
    assert db_patients[0].session_code == "A1"
    assert db_patients[0].doctor_name == "A"
    assert db_patients[1].session_code == "A2"
    assert db_patients[1].doctor_name == "B"


@pytest.mark.asyncio
async def test_sync_from_appsheet_with_reset(session: AsyncSession):
    """sync_from_appsheet with reset=True clears active patients first."""
    await session.execute(delete(ExamOrder))
    await session.execute(delete(Patient))
    await session.commit()

    # Pre-create an active patient
    pre_existing = Patient(
        name="Existing", species="Canino", sex="Macho",
        owner_name="Someone", source=PatientSource.MANUAL.value,
        session_code="OLD", sources_received=[PatientSource.MANUAL.value],
        normalized_name="existing", normalized_owner="someone",
        waiting_room_status="active",
    )
    session.add(pre_existing)
    await session.commit()

    sync_svc = AppSheetSyncService()
    patients = [
        AppSheetPatient(
            Codigo_Corto="A1", Doctora="A", Categoria_Examen="E",
            Examen_Especifico="S", Nombre_Mascota="N1", Especie="Felino",
            Sexo="M", Edad_Numero="1", Edad_Unidad="A",
            Nombre_Tutor="T1", Raza="R1",
        ),
    ]

    count = await sync_svc.sync_from_appsheet(patients, session, reset=True)
    assert count == 1

    # Old patient should be deleted
    result = await session.execute(
        select(Patient).where(Patient.session_code == "OLD")
    )
    assert result.scalar_one_or_none() is None

    # New patient should exist
    result = await session.execute(
        select(Patient).where(Patient.session_code == "A1")
    )
    assert result.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_clear_all_active_patients(session: AsyncSession):
    """clear_all_active_patients deletes all active patients."""
    await session.execute(delete(ExamOrder))
    await session.execute(delete(Patient))
    await session.commit()

    # Create active patients
    for i in range(3):
        session.add(Patient(
            name=f"P{i}", species="Canino", sex="Macho",
            owner_name="Owner", source=PatientSource.MANUAL.value,
            session_code=f"TEST{i}", sources_received=[PatientSource.MANUAL.value],
            normalized_name=f"p{i}", normalized_owner="owner",
            waiting_room_status="active",
        ))
    # Create one archived patient (should NOT be deleted)
    session.add(Patient(
        name="Archived", species="Canino", sex="Macho",
        owner_name="Owner", source=PatientSource.MANUAL.value,
        session_code="ARCH", sources_received=[PatientSource.MANUAL.value],
        normalized_name="archived", normalized_owner="owner",
        waiting_room_status="archived",
    ))
    await session.commit()

    sync_svc = AppSheetSyncService()
    count = await sync_svc.clear_all_active_patients(session)
    assert count == 3

    # Verify only archived remains
    result = await session.execute(
        select(Patient).order_by(Patient.session_code)
    )
    remaining = result.scalars().all()
    assert len(remaining) == 1
    assert remaining[0].session_code == "ARCH"
    assert remaining[0].waiting_room_status == "archived"
