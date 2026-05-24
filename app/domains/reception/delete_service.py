from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select as sa_select
from sqlalchemy.orm import selectinload
from app.domains.patients.models import Patient
from app.shared.models.test_result import TestResult
from app.shared.models.lab_value import LabValue
from app.shared.models.patient_image import PatientImage
import logfire


class PatientDeleteService:
    """Handles hard-delete of a patient record with full cascade."""

    async def delete_patient_from_waiting_room(
        self, patient_id: int, session: AsyncSession
    ) -> bool:
        """
        Deletes a patient record from the database.

        Returns True if the patient was found and deleted, False otherwise.
        """
        logfire.info(f"Attempting to delete patient with id={patient_id}")

        # Cargar toda la cadena en memoria para que el cascade ORM funcione:
        # Patient → TestResult → LabValue / PatientImage
        stmt = (
            sa_select(Patient)
            .where(Patient.id == patient_id)
            .options(
                selectinload(Patient.test_results).options(
                    selectinload(TestResult.lab_values),
                    selectinload(TestResult.images),
                )
            )
        )
        result = await session.execute(stmt)
        patient = result.scalar_one_or_none()

        if patient:
            await session.delete(patient)
            await session.commit()
            logfire.info(f"Successfully deleted patient with id={patient_id}")
            return True
        else:
            logfire.warning(f"Patient with id={patient_id} not found for deletion.")
            return False
