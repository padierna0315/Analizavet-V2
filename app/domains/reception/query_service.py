from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from app.domains.patients.models import Patient
from app.domains.exam_order.service import ExamOrderService


class WaitingRoomQueryService:
    """Handles waiting room patient queries — pure read, no side effects."""

    def __init__(self):
        self._exam_order_service = ExamOrderService()

    async def get_waiting_room_patients(
        self, session: AsyncSession
    ) -> list[dict]:
        """Get all patients currently in the waiting room (sala de espera).

        Returns patients with waiting_room_status = 'active' formatted for display.
        """
        from app.shared.models.test_result import TestResult
        query = select(Patient).where(Patient.waiting_room_status == "active")
        query = query.order_by(Patient.updated_at.desc())

        result = await session.execute(query)
        patients = result.scalars().all()

        # Format patient data for the waiting room UI
        patients_data = []
        for patient in patients:
            sources_received = list(patient.sources_received or [])

            # Get the most recent TestResult id for this patient
            tr_query = (
                select(TestResult.id)
                .where(TestResult.patient_id == patient.id)
                .order_by(TestResult.id.desc())
                .limit(1)
            )
            tr_result = await session.execute(tr_query)
            latest_result_id = tr_result.scalar_one_or_none()

            # ── Look up active ExamOrders ─────────────────────────────
            exam_orders_list: list[dict] = []
            orders = await self._exam_order_service.get_by_patient(patient.id, session)
            for order in orders:
                exam_orders_list.append({
                    "id": order.id,
                    "session_code": order.session_code,
                    "exam_types": order.exam_types,
                    "status": order.status,
                })

            patient_data = {
                "id": patient.id,
                "result_id": latest_result_id,
                "name": patient.name,
                "species": patient.species,
                "sex": patient.sex,
                "owner_name": patient.owner_name,
                "age_display": patient.age_display,
                "session_code": patient.session_code,
                "waiting_room_status": patient.waiting_room_status,
                "sources_received": sources_received,
                "exam_orders": exam_orders_list,
                "appsheet_test_type": patient.appsheet_test_type,
                "appsheet_test_type_code": patient.appsheet_test_type_code,
                "created_at": patient.created_at.isoformat() if patient.created_at else None,
                "updated_at": patient.updated_at.isoformat() if patient.updated_at else None,
                "source": patient.source,
                "normalized_name": patient.normalized_name,
                "normalized_owner": patient.normalized_owner,
            }
            patients_data.append(patient_data)

        return patients_data

    async def get_single_patient_for_card(
        self, patient_id: int, session: AsyncSession
    ) -> dict | None:
        """Gets a single patient's data formatted for the waiting room card."""
        patient = await session.get(Patient, patient_id)
        if not patient:
            return None

        # This logic is duplicated from get_waiting_room_patients.
        # Consider refactoring into a helper function in the future.
        # sources_received is now a Python list (TypeDecorator handles deserialization)
        sources_received = list(patient.sources_received or [])

        # Check for latest TestResult
        from app.shared.models.test_result import TestResult
        from sqlmodel import select
        tr_stmt = select(TestResult.id).where(TestResult.patient_id == patient.id).order_by(TestResult.id.desc()).limit(1)
        tr_result = await session.execute(tr_stmt)
        latest_result_id = tr_result.scalar_one_or_none()

        # ── Look up active ExamOrders ─────────────────────────────────
        exam_orders_list: list[dict] = []
        orders = await self._exam_order_service.get_by_patient(patient.id, session)
        for order in orders:
            exam_orders_list.append({
                "id": order.id,
                "session_code": order.session_code,
                "exam_types": order.exam_types,
                "status": order.status,
            })

        patient_data = {
            "id": patient.id,
            "name": patient.name,
            "species": patient.species,
            "sex": patient.sex,
            "owner_name": patient.owner_name,
            "age_display": patient.age_display,
            "session_code": patient.session_code,
            "result_id": latest_result_id,
            "waiting_room_status": patient.waiting_room_status,
            "sources_received": sources_received,
            "exam_orders": exam_orders_list,
            "appsheet_test_type": patient.appsheet_test_type,
            "appsheet_test_type_code": patient.appsheet_test_type_code,
            "created_at": patient.created_at.isoformat() if patient.created_at else None,
            "updated_at": patient.updated_at.isoformat() if patient.updated_at else None,
            "source": patient.source,
            "normalized_name": patient.normalized_name,
            "normalized_owner": patient.normalized_owner,
        }
        return patient_data
