"""
Algorithm Registry — pure clinical mathematics, no DB, no side effects.

Each algorithm takes a list of LabValues and returns a computed LabValue
plus its interpretation key (to be resolved against the interpretations dict).

Santiago's research-powered formulas:
  - Ratio Na:K
  - Ratio BUN/Creatinina
  - Índice de Mentzer
  - Calcio Corregido por Albúmina
"""
from app.shared.models.lab_value import LabValue
from app.shared.algorithms.unit_validation import get_validated_value
from app.shared.algorithms.interpretations import INTERPRETATIONS
from dataclasses import dataclass


@dataclass
class AlgorithmResult:
    """A computed algorithm result — not yet saved to DB."""
    lab_value: LabValue
    interpretation_key: str


@dataclass
class AlgorithmError:
    """Something went wrong inside one algorithm — does NOT stop other algorithms."""
    algorithm_name: str
    reason: str


class AlgorithmRegistry:
    """Runs all clinical algorithms safely, collecting results and errors."""

    def __init__(self):
        self._algorithms = [
            self._ratio_na_k,
            self._ratio_bun_cre,
            self._indice_mentzer,
            self._calcio_corregido,
        ]

    def run_all(
        self, lab_values: list[LabValue]
    ) -> tuple[list[AlgorithmResult], list[AlgorithmError]]:
        """Run every algorithm, collecting successes and failures independently."""
        results: list[AlgorithmResult] = []
        errors: list[AlgorithmError] = []

        for algo in self._algorithms:
            try:
                result = algo(lab_values)
                if result is not None:
                    results.append(result)
            except Exception as exc:  # noqa: BLE001
                errors.append(AlgorithmError(
                    algorithm_name=algo.__name__,
                    reason=str(exc),
                ))

        return results, errors

    # ── Individual algorithms ────────────────────────────────────────────────

    def _ratio_na_k(self, values: list[LabValue]) -> AlgorithmResult | None:
        """Ratio Na:K = Na / K.

        Requires:
          - NA: mEq/L or mmol/L
          - K:  mEq/L or mmol/L
        Flag: BAJO if < 27, else NORMAL.
        """
        na = get_validated_value(values, "NA", ["mEq/L", "mmol/L"])
        k = get_validated_value(values, "K", ["mEq/L", "mmol/L"])

        if na is None or k is None or k == 0:
            return None

        val = round(na / k, 2)
        flag = "BAJO" if val < 27 else "NORMAL"
        interp_key = "RATIO_NA_K_BAJO" if flag == "BAJO" else "RATIO_NA_K_NORMAL"

        lv = LabValue(
            parameter_code="RATIO_NA_K",
            parameter_name_es="Ratio Na:K",
            raw_value=str(val),
            numeric_value=val,
            unit="ratio",
            reference_range="27:1 - 40:1",
            flag=flag,
        )
        return AlgorithmResult(lab_value=lv, interpretation_key=interp_key)

    def _ratio_bun_cre(self, values: list[LabValue]) -> AlgorithmResult | None:
        """Ratio BUN/Creatinina = BUN / CRE.

        Requires:
          - BUN: mg/dL
          - CRE: mg/dL
        Flag: ALTO if > 30, else NORMAL.
        """
        bun = get_validated_value(values, "BUN", ["mg/dL"])
        cre = get_validated_value(values, "CRE", ["mg/dL"])

        if bun is None or cre is None or cre == 0:
            return None

        val = round(bun / cre, 2)
        flag = "ALTO" if val > 30 else "NORMAL"
        interp_key = "RATIO_BUN_CRE_ALTO" if flag == "ALTO" else "RATIO_BUN_CRE_NORMAL"

        lv = LabValue(
            parameter_code="RATIO_BUN_CRE",
            parameter_name_es="Ratio BUN/Creatinina",
            raw_value=str(val),
            numeric_value=val,
            unit="ratio",
            reference_range="≤30:1",
            flag=flag,
        )
        return AlgorithmResult(lab_value=lv, interpretation_key=interp_key)

    def _indice_mentzer(self, values: list[LabValue]) -> AlgorithmResult | None:
        """Índice de Mentzer = MCV / RBC.

        Requires:
          - MCV: fL
          - RBC: 10^6/uL or 10*6/uL or 10^12/L
        Flag: BAJO if < 13, else NORMAL.
        """
        mcv = get_validated_value(values, "MCV", ["fL"])
        rbc = get_validated_value(values, "RBC", ["10^6/uL", "10*6/uL", "10^12/L"])

        if mcv is None or rbc is None or rbc == 0:
            return None

        val = round(mcv / rbc, 2)
        flag = "BAJO" if val < 13 else "NORMAL"
        interp_key = "MENTZER_BAJO" if flag == "BAJO" else "MENTZER_NORMAL"

        lv = LabValue(
            parameter_code="INDICE_MENTZER",
            parameter_name_es="Índice de Mentzer",
            raw_value=str(val),
            numeric_value=val,
            unit="ratio",
            reference_range="≥13",
            flag=flag,
        )
        return AlgorithmResult(lab_value=lv, interpretation_key=interp_key)

    def _calcio_corregido(self, values: list[LabValue]) -> AlgorithmResult | None:
        """Calcio Corregido = Ca + 0.8 * (4.0 - ALB).

        Requires:
          - Ca:  mg/dL
          - ALB: g/dL
        Flag: NORMAL (calculated value — flagging is for display only).
        """
        ca = get_validated_value(values, "CA", ["mg/dL"])
        alb = get_validated_value(values, "ALB", ["g/dL"])

        if ca is None or alb is None:
            return None

        val = round(ca + 0.8 * (4.0 - alb), 2)
        # Determine flag based on typical reference range (8.5-10.5 mg/dL)
        if val < 8.5:
            flag = "BAJO"
        elif val > 10.5:
            flag = "ALTO"
        else:
            flag = "NORMAL"

        lv = LabValue(
            parameter_code="CALCIO_CORREGIDO",
            parameter_name_es="Calcio Corregido",
            raw_value=str(val),
            numeric_value=val,
            unit="mg/dL",
            reference_range="8.5-10.5 mg/dL",
            flag=flag,
        )
        return AlgorithmResult(lab_value=lv, interpretation_key="CALCIO_CORREGIDO")
