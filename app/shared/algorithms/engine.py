"""
Clinical Algorithms Engine — orchestrates the registry with DB persistence.

This is the only part of the algorithms domain that touches SQLAlchemy.
Pure algorithm logic lives in registry.py (no framework deps).
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import logfire

from app.shared.models.test_result import TestResult
from app.shared.models.lab_value import LabValue
from app.shared.algorithms.registry import AlgorithmRegistry, AlgorithmResult, AlgorithmError
from app.shared.algorithms.interpretations import INTERPRETATIONS


class ClinicalAlgorithmsEngine:
    """Applies clinical algorithms to a TestResult and persists new LabValues."""

    def __init__(self):
        self._registry = AlgorithmRegistry()

    async def apply_algorithms(
        self, test_result_id: int, session: AsyncSession
    ) -> dict:
        """Run all algorithms for a TestResult and persist the results.

        Returns:
            dict with:
              - new_values: list of computed LabValue dicts (ready for PDF)
              - interpretations: list of interpretation texts (from the archivero)
              - errors: list of error messages per algorithm
        """
        # 1. Fetch TestResult and its LabValues
        test_result = await session.get(TestResult, test_result_id)
        if test_result is None:
            raise ValueError(f"TestResult {test_result_id} no encontrado.")

        # Load lab_values explicitly (async-compatible) — avoids SQLAlchemy lazy-load
        # issue where sync relationship access fails in async session context
        lv_result = await session.execute(
            select(LabValue).where(LabValue.test_result_id == test_result_id)
        )
        lab_values = list(lv_result.scalars().all())

        # 2. Run registry
        algorithm_results, algorithm_errors = self._registry.run_all(lab_values)

        # 3. Persist new LabValues to DB
        new_values = []
        interpretations = []

        for ar in algorithm_results:
            lv = ar.lab_value
            lv.test_result_id = test_result_id
            session.add(lv)
            new_values.append(lv)

            # Resolve interpretation from the archivero
            interp = INTERPRETATIONS.get(ar.interpretation_key)
            if interp:
                interpretations.append({
                    "parameter_code": lv.parameter_code,
                    "parameter_name_es": lv.parameter_name_es,
                    "flag": lv.flag,
                    "text_es": interp["text_es"],
                    "severity": interp["severity"],
                })

        if new_values:
            await session.commit()
            for lv in new_values:
                await session.refresh(lv)
            logfire.info(
                f"Algorithms applied to TestResult {test_result_id}: "
                f"{len(new_values)} new LabValues, {len(algorithm_errors)} errors."
            )

        return {
            "new_values": [
                {
                    "parameter_code": lv.parameter_code,
                    "parameter_name_es": lv.parameter_name_es,
                    "numeric_value": lv.numeric_value,
                    "unit": lv.unit,
                    "reference_range": lv.reference_range,
                    "flag": lv.flag,
                }
                for lv in new_values
            ],
            "interpretations": interpretations,
            "errors": [
                {"algorithm": e.algorithm_name, "reason": e.reason}
                for e in algorithm_errors
            ],
        }
