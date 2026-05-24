from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from app.domains.patients.models import Patient
from app.shared.models.test_result import TestResult
from app.shared.models.lab_value import LabValue
from app.domains.exam_order.service import ExamOrderService
from app.domains.reception.helpers import _resolve_test_type_from_exam_types
import logfire


class TestResultMergeService:
    """Handles TestResult merging for Taller workshop injection.

    Loads ALL TestResults for a patient, merges them into a single unified
    TestResult with dedup (first-wins), flag recount, doctor propagation,
    and test_type propagation from ExamOrder.
    """

    def __init__(self):
        self._exam_order_service = ExamOrderService()

    async def inject_patient_to_taller(
        self, patient_id: int, session: AsyncSession
    ) -> TestResult | None:
        """
        Loads ALL TestResults for a patient, merges them into a single TestResult,
        and returns the unified result for the Taller workspace.

        Handles:
        - Multiple sources (Ozelle + Fujifilm) → merged into one TR
        - Multiple parameters from same source (CRE + ALT) → merged into one TR
        - Duplicate parameters → skipped (first wins)
        - Race conditions → idempotent (merge always produces same result)
        """
        logfire.info(f"Attempting to inject patient {patient_id} test results to Taller.")

        # Load ALL TestResults for this patient (newest first)
        statement = (
            select(TestResult)
            .where(TestResult.patient_id == patient_id)
            .order_by(TestResult.id.desc())
        )
        result = await session.execute(statement)
        test_results = result.scalars().all()

        if not test_results:
            logfire.warning(f"No TestResult found for patient {patient_id}.")
            return None

        # Load Patient para datos de AppSheet (doctor_name)
        patient_result = await session.execute(select(Patient).where(Patient.id == patient_id))
        patient = patient_result.scalar_one_or_none()
        doctor_name = patient.doctor_name if patient else None

        # Resolve test_type from active ExamOrder first, fall back to Patient.appsheet_test_type
        exam_orders = await self._exam_order_service.get_by_patient(patient_id, session)
        active_orders = [o for o in exam_orders if o.status in ("pending", "partial")]
        exam_type_result = None
        if active_orders:
            exam_type_result = _resolve_test_type_from_exam_types(active_orders[0].exam_types)

        if exam_type_result:
            appsheet_test_type, appsheet_test_type_code = exam_type_result
        else:
            appsheet_test_type = patient.appsheet_test_type if patient else None
            appsheet_test_type_code = patient.appsheet_test_type_code if patient else None

        if len(test_results) == 1:
            # Single TR — nothing to merge, return as-is with doctor_name + exam type
            tr = test_results[0]
            if doctor_name and not tr.doctor_name:
                tr.doctor_name = doctor_name
            if appsheet_test_type:
                tr.test_type = appsheet_test_type
                tr.test_type_code = appsheet_test_type_code or tr.test_type_code
            if doctor_name or appsheet_test_type:
                session.add(tr)
                await session.commit()
                await session.refresh(tr)
            logfire.info(f"Found TestResult {tr.id} (status={tr.status}) for patient {patient_id}.")
            return tr

        # Multiple TRs — merge all into the LATEST one
        target_tr = test_results[0]
        merged_sources = {target_tr.source}

        for tr in test_results[1:]:
            merged_sources.add(tr.source)

            # Load LabValues from this older TR
            older_lvs = await session.execute(
                select(LabValue).where(LabValue.test_result_id == tr.id)
            )

            for lv in older_lvs.scalars().all():
                # Skip if this parameter_code already exists in target TR
                dup_check = await session.execute(
                    select(LabValue).where(
                        LabValue.test_result_id == target_tr.id,
                        LabValue.parameter_code == lv.parameter_code,
                    )
                )
                if dup_check.scalars().first() is not None:
                    logfire.info(
                        f"Skipping duplicate {lv.parameter_code} from TestResult {tr.id} "
                        f"(already in TestResult {target_tr.id})"
                    )
                    continue

                # Copy LabValue to target TR (create new, don't reparent — avoids cascade complexity)
                new_lv = LabValue(
                    test_result_id=target_tr.id,
                    parameter_code=lv.parameter_code,
                    parameter_name_es=lv.parameter_name_es,
                    raw_value=lv.raw_value,
                    numeric_value=lv.numeric_value,
                    unit=lv.unit,
                    reference_range=lv.reference_range,
                    flag=lv.flag,
                    machine_flag=lv.machine_flag,
                )
                session.add(new_lv)

            # Delete the old TR (cascade deletes its now-redundant LabValues)
            await session.delete(tr)

        # Update target TR source to reflect merged provenance
        target_tr.source = ",".join(sorted(merged_sources))

        # Recalculate flag counts based on ALL merged LabValues
        all_lvs = await session.execute(
            select(LabValue).where(LabValue.test_result_id == target_tr.id)
        )
        flags = [lv.flag for lv in all_lvs.scalars().all()]
        target_tr.flag_alto_count = flags.count("ALTO")
        target_tr.flag_normal_count = flags.count("NORMAL")
        target_tr.flag_bajo_count = flags.count("BAJO")

        # Propagar doctor_name desde el Patient al TestResult unificado
        if doctor_name and not target_tr.doctor_name:
            target_tr.doctor_name = doctor_name

        # Propagar test_type desde ExamOrder (o Patient.appsheet_test_type) al TestResult
        if appsheet_test_type:
            target_tr.test_type = appsheet_test_type
            target_tr.test_type_code = appsheet_test_type_code or target_tr.test_type_code

        await session.commit()
        await session.refresh(target_tr)

        logfire.info(
            f"Merged {len(test_results)} TestResults into TestResult {target_tr.id} "
            f"(sources: {target_tr.source}, params: {len(flags)}) for patient {patient_id}."
        )
        return target_tr
