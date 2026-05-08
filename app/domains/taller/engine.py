from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
import logfire

from app.shared.models.test_result import TestResult
from app.shared.models.lab_value import LabValue
from app.domains.taller.flagging import ClinicalFlaggingService
from app.domains.taller.schemas import FlagBatchRequest, FlagBatchResult, RawLabValueInput
from app.core.reference import get_reference_range


class TallerFlaggingEngine:
    """Applies clinical flagging to all lab values in a TestResult.

    Flow:
    1. Receive TestResult ID + raw values + species
    2. Flag each value with ClinicalFlaggingService
    3. Save LabValue rows to DB
    4. Update TestResult counts + status → "listo"
    5. Return FlagBatchResult with summary
    """

    def __init__(self):
        self._flagging = ClinicalFlaggingService()

    async def flag_test_result(
        self,
        request: FlagBatchRequest,
        session: AsyncSession,
    ) -> FlagBatchResult:
        # 1. Verify TestResult exists
        test_result = await self._get_test_result(request.test_result_id, session)
        if not test_result:
            raise ValueError(
                f"TestResult con ID {request.test_result_id} no encontrado"
            )

        # 2. Flag all values
        # IMPORTANT: numeric_value=None means the analyzer sent a non-numeric result
        # (e.g., "Negative", "Trace", "+"). Never substitute 0.0 — that would produce
        # a clinically incorrect BAJO flag (WBC=0 is biologically impossible).
        flagged: list[FlagResult] = []
        for raw in request.values:
            if raw.numeric_value is None:
                # Non-numeric result: keep as NORMAL with a warning
                logfire.warning(
                    f"Valor no numérico para {raw.parameter_code}: '{raw.raw_value}'. "
                    f"Se asigna flag=NORMAL. Verificar manualmente."
                )
                flag_result = FlagResult(
                    parameter=raw.parameter_code,
                    value=0.0,
                    unit=raw.unit,
                    flag="NORMAL",
                    reference_range=get_reference_range(raw.parameter_code, request.species),
                )
            else:
                flag_result = self._flagging.flag_value(
                    parameter=raw.parameter_code,
                    value=raw.numeric_value,
                    unit=raw.unit,
                    species=request.species,
                )
            flagged.append(flag_result)

        # 3. Save LabValue rows to DB
        for raw, flag_result in zip(request.values, flagged):
            lab_value = LabValue(
                test_result_id=request.test_result_id,
                parameter_code=raw.parameter_code,
                parameter_name_es=raw.parameter_name_es,
                raw_value=raw.raw_value,
                numeric_value=raw.numeric_value,
                unit=raw.unit,
                reference_range=get_reference_range(raw.parameter_code, request.species),
                flag=flag_result.flag,
                machine_flag=raw.machine_flag,
            )
            session.add(lab_value)

        # 4. Compute summary
        summary = {"ALTO": 0, "NORMAL": 0, "BAJO": 0}
        for fr in flagged:
            summary[fr.flag] += 1

        # 5. Update TestResult
        test_result.flag_alto_count = summary["ALTO"]
        test_result.flag_normal_count = summary["NORMAL"]
        test_result.flag_bajo_count = summary["BAJO"]
        test_result.status = "listo"
        test_result.processed_at = datetime.now(timezone.utc)
        session.add(test_result)

        await session.commit()
        await session.refresh(test_result)

        logfire.info(
            f"TestResult {request.test_result_id} procesado: "
            f"ALTO={summary['ALTO']} NORMAL={summary['NORMAL']} BAJO={summary['BAJO']}"
        )

        return FlagBatchResult(
            test_result_id=request.test_result_id,
            flagged_values=flagged,
            summary=summary,
            status="listo",
        )

    async def _get_test_result(
        self, test_result_id: int, session: AsyncSession
    ) -> TestResult | None:
        result = await session.execute(
            select(TestResult).where(TestResult.id == test_result_id)
        )
        return result.scalars().first()