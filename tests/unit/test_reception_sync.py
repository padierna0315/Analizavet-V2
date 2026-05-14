import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, delete
from app.domains.reception.service import ReceptionService
from app.services.appsheet import AppSheetPatient
from app.domains.patients.models import Patient
from app.domains.exam_order.models import ExamOrder
from app.domains.reception.schemas import PatientSource


# ── Redis Counter Helpers (Task 2.1) ─────────────────────────────────────────

class TestUploadCounter:
    """Tests for init_upload_counter and decrement_upload_counter in hl7_processor."""

    @pytest.fixture(autouse=True)
    def mock_redis(self):
        """Mock redis.from_url for all tests."""
        self.mock_conn = MagicMock()
        with patch('app.tasks.hl7_processor.redis.from_url', return_value=self.mock_conn):
            yield

    def test_init_upload_counter_sets_pending(self):
        """init_upload_counter sets upload:pending with TTL=300."""
        from app.tasks.hl7_processor import init_upload_counter
        init_upload_counter("test-upload-1", 5)
        self.mock_conn.setex.assert_called_once_with("upload:test-upload-1:pending", 300, 5)

    def test_decrement_upload_counter_reaches_zero(self):
        """decrement_upload_counter: when DECR returns 0, sets complete status."""
        from app.tasks.hl7_processor import decrement_upload_counter, set_upload_status
        self.mock_conn.decr.return_value = 0

        with patch('app.tasks.hl7_processor.set_upload_status') as mock_set_status:
            decrement_upload_counter("test-upload-1")
            self.mock_conn.decr.assert_called_once_with("upload:test-upload-1:pending")
            self.mock_conn.delete.assert_called_once_with("upload:test-upload-1:pending")
            mock_set_status.assert_called_once_with("test-upload-1", "complete:")

    def test_decrement_upload_counter_negative_becomes_zero(self):
        """decrement_upload_counter: when DECR returns negative, also completes."""
        from app.tasks.hl7_processor import decrement_upload_counter
        self.mock_conn.decr.return_value = -2

        with patch('app.tasks.hl7_processor.set_upload_status') as mock_set_status:
            decrement_upload_counter("test-upload-1")
            self.mock_conn.decr.assert_called_once_with("upload:test-upload-1:pending")
            self.mock_conn.delete.assert_called_once_with("upload:test-upload-1:pending")
            mock_set_status.assert_called_once_with("test-upload-1", "complete:")

    def test_decrement_upload_counter_still_processing(self):
        """decrement_upload_counter: when DECR returns >0, no completion."""
        from app.tasks.hl7_processor import decrement_upload_counter
        self.mock_conn.decr.return_value = 3

        with patch('app.tasks.hl7_processor.set_upload_status') as mock_set_status:
            decrement_upload_counter("test-upload-1")
            self.mock_conn.decr.assert_called_once_with("upload:test-upload-1:pending")
            self.mock_conn.delete.assert_not_called()
            mock_set_status.assert_not_called()

@pytest.mark.asyncio
async def test_sync_from_appsheet_new_patient(session: AsyncSession):
    # Clear tables first to avoid MultipleResultsFound and orphan ExamOrders
    await session.execute(delete(ExamOrder))
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
    assert patient.doctor_name == "Aura"
    # AppSheet test_type: "Perfil Básico (PQ1)" no está en el mapa exacto → fallback a default
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
    # "Perfil Básico (PQ1)" should resolve via the fuzzy matcher
    assert len(order.exam_types) > 0


@pytest.mark.asyncio
async def test_sync_from_appsheet_new_patient_mapped_type(session: AsyncSession):
    """Verifica que Examen_Especifico con valores del mapa se resuelve correctamente."""
    await session.execute(delete(ExamOrder))
    await session.execute(delete(Patient))
    await session.commit()

    service = ReceptionService()

    appsheet_patients = [
        AppSheetPatient(
            Codigo_Corto="R1",
            Doctora="Aura",
            Categoria_Examen="Examen de sangre",
            Examen_Especifico="Perfil Renal",
            Nombre_Mascota="Rex",
            Especie="Canino",
            Sexo="Macho",
            Edad_Numero="5",
            Edad_Unidad="Años",
            Nombre_Tutor="Juan Perez",
            Raza="Labrador"
        ),
        AppSheetPatient(
            Codigo_Corto="C1",
            Doctora="Luis",
            Categoria_Examen="Coprologico",
            Examen_Especifico="Coprologico seriado 1",
            Nombre_Mascota="Milo",
            Especie="Canino",
            Sexo="Macho",
            Edad_Numero="3",
            Edad_Unidad="Años",
            Nombre_Tutor="Maria Lopez",
            Raza="Mestizo"
        ),
    ]

    await service.sync_from_appsheet(appsheet_patients, session)

    # Verificar Perfil Renal
    result = await session.execute(select(Patient).where(Patient.session_code == "R1"))
    p1 = result.scalar_one_or_none()
    assert p1 is not None
    assert p1.appsheet_test_type == "Perfil Renal"
    assert p1.appsheet_test_type_code == "CHEM"

    # Verificar Coprologico seriado 1
    result = await session.execute(select(Patient).where(Patient.session_code == "C1"))
    p2 = result.scalar_one_or_none()
    assert p2 is not None
    assert p2.appsheet_test_type == "Coprológico Seriado 1"
    assert p2.appsheet_test_type_code == "COPROSC"

    # Verify ExamOrders were created with correct exam_types
    order_result = await session.execute(
        select(ExamOrder).where(ExamOrder.session_code == "R1")
    )
    r1_order = order_result.scalar_one_or_none()
    assert r1_order is not None
    assert r1_order.patient_id == p1.id
    # "Perfil Renal" resolves to CHEM_RENAL
    assert "CHEM_RENAL" in r1_order.exam_types

    order_result = await session.execute(
        select(ExamOrder).where(ExamOrder.session_code == "C1")
    )
    c1_order = order_result.scalar_one_or_none()
    assert c1_order is not None
    assert c1_order.patient_id == p2.id
    # "Coprologico seriado 1" fuzzy-matches to "Coprologico Seriado 2" (COPROSC_SERIADO_2)
    # because the catalog has no exact alias for "seriado 1"
    assert "COPROSC_SERIADO_2" in c1_order.exam_types

@pytest.mark.asyncio
async def test_sync_from_appsheet_update_existing(session: AsyncSession):
    # Clear tables first
    await session.execute(delete(ExamOrder))
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
    assert patient.doctor_name == "Aura"
    assert patient.appsheet_test_type == "Química Sanguínea"  # fallback: "Perfil Básico (PQ1)" no está en mapa exacto
    assert patient.appsheet_test_type_code == "CHEM"
    assert PatientSource.APPSHEET.value in patient.sources_received
    assert PatientSource.LIS_OZELLE.value in patient.sources_received
    assert patient.breed == "Mestizo"

    # Verify ExamOrder was created/updated
    order_result = await session.execute(
        select(ExamOrder).where(ExamOrder.session_code == "A1")
    )
    order = order_result.scalar_one_or_none()
    assert order is not None
    assert order.patient_id == patient.id
    assert order.status == "pending"

@pytest.mark.asyncio
async def test_sync_from_appsheet_multiple(session: AsyncSession):
    await session.execute(delete(ExamOrder))
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
    assert patients[0].doctor_name == "A"
    assert patients[0].appsheet_test_type == "Química Sanguínea"  # fallback
    assert patients[1].session_code == "A2"
    assert patients[1].doctor_name == "B"
    assert patients[1].appsheet_test_type == "Química Sanguínea"  # fallback

    # Verify ExamOrders were created for each patient
    orders_result = await session.execute(select(ExamOrder).order_by(ExamOrder.session_code))
    orders = orders_result.scalars().all()
    assert len(orders) == 2
    assert orders[0].session_code == "A1"
    assert orders[0].patient_id == patients[0].id
    assert orders[1].session_code == "A2"
    assert orders[1].patient_id == patients[1].id
