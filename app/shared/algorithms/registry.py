"""
Algorithm Registry — pure clinical mathematics, no DB, no side effects.

Each algorithm takes a list of LabValues and returns a computed LabValue
plus its interpretation key (to be resolved against the interpretations dict).

Santiago's research-powered formulas:
  - Ratio Na:K
  - Ratio BUN/Creatinina
  - Índice de Mentzer
  - Calcio Corregido por Albúmina

REFERENCE RANGES and FLAGS are sourced from clinical_standards.py (single source of truth).
"""
from app.shared.models.lab_value import LabValue
from app.shared.algorithms.unit_validation import get_validated_value
from app.shared.algorithms.interpretations import INTERPRETATIONS
from clinical_standards import VETERINARY_STANDARDS, STANDARDS_MAPPING
from dataclasses import dataclass


# Species name mapping (same as ClinicalFlaggingService)
_SPECIES_MAP = {
    "Canino": "canine",
    "Canina": "canine",
    "Felino": "feline",
    "Felina": "feline",
}


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
        self, lab_values: list[LabValue], species: str = "Canino"
    ) -> tuple[list[AlgorithmResult], list[AlgorithmError]]:
        """Run every algorithm, collecting successes and failures independently.

        Args:
            lab_values: List of LabValues from the test result.
            species: Species string ("Canino" or "Felino") for reference range lookup.
        """
        results: list[AlgorithmResult] = []
        errors: list[AlgorithmError] = []

        for algo in self._algorithms:
            try:
                result = algo(lab_values, species)
                if result is not None:
                    results.append(result)
            except Exception as exc:  # noqa: BLE001
                errors.append(AlgorithmError(
                    algorithm_name=algo.__name__,
                    reason=str(exc),
                ))

        return results, errors

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _get_species_key(species: str) -> str | None:
        """Normalize DB species string to clinical_standards key."""
        return _SPECIES_MAP.get(species, "canine")

    @staticmethod
    def _build_reference_range(code: str, species: str) -> str:
        """Build reference range string from clinical_standards (single source of truth)."""
        resolved = STANDARDS_MAPPING.get(code, code)
        param = VETERINARY_STANDARDS.get(resolved)
        if not param:
            return ""
        species_key = _SPECIES_MAP.get(species, "canine")
        ranges = param.get("ranges", {}).get(species_key)
        if not ranges or "min" not in ranges or "max" not in ranges:
            return ""
        unit = param.get("unit", "")
        return f"{ranges['min']} - {ranges['max']} {unit}".strip()

    @staticmethod
    def _determine_flag(code: str, value: float, species: str) -> str:
        """Determine flag (ALTO/BAJO/NORMAL) from clinical_standards ranges."""
        resolved = STANDARDS_MAPPING.get(code, code)
        param = VETERINARY_STANDARDS.get(resolved)
        if not param:
            return "NORMAL"
        species_key = _SPECIES_MAP.get(species, "canine")
        ranges = param.get("ranges", {}).get(species_key)
        if not ranges or "min" not in ranges or "max" not in ranges:
            return "NORMAL"
        if value < ranges["min"]:
            return "BAJO"
        if value > ranges["max"]:
            return "ALTO"
        return "NORMAL"

    # ── Individual algorithms ────────────────────────────────────────────────

    def _ratio_na_k(self, values: list[LabValue], species: str) -> AlgorithmResult | None:
        """Ratio Na:K = Na / K.

        Requires:
          - NA: mEq/L or mmol/L
          - K:  mEq/L or mmol/L
        Flag and range sourced from clinical_standards (RATIO_NA_K).
        """
        na = get_validated_value(values, "NA", ["mEq/L", "mmol/L"])
        k = get_validated_value(values, "K", ["mEq/L", "mmol/L"])

        if na is None or k is None or k == 0:
            return None

        val = round(na / k, 2)
        flag = self._determine_flag("RATIO_NA_K", val, species)
        ref_range = self._build_reference_range("RATIO_NA_K", species)
        interp_key = f"RATIO_NA_K_{flag}"

        lv = LabValue(
            parameter_code="RATIO_NA_K",
            parameter_name_es="Ratio Na:K",
            raw_value=str(val),
            numeric_value=val,
            unit="ratio",
            reference_range=ref_range,
            flag=flag,
        )
        return AlgorithmResult(lab_value=lv, interpretation_key=interp_key)

    def _ratio_bun_cre(self, values: list[LabValue], species: str) -> AlgorithmResult | None:
        """Ratio BUN/Creatinina = BUN / CRE.

        Requires:
          - BUN: mg/dL
          - CRE: mg/dL
        Flag and range sourced from clinical_standards (RATIO_BUN_CRE).
        """
        bun = get_validated_value(values, "BUN", ["mg/dL"])
        cre = get_validated_value(values, "CRE", ["mg/dL"])

        if bun is None or cre is None or cre == 0:
            return None

        val = round(bun / cre, 2)
        flag = self._determine_flag("RATIO_BUN_CRE", val, species)
        ref_range = self._build_reference_range("RATIO_BUN_CRE", species)
        interp_key = f"RATIO_BUN_CRE_{flag}"

        lv = LabValue(
            parameter_code="RATIO_BUN_CRE",
            parameter_name_es="Ratio BUN/Creatinina",
            raw_value=str(val),
            numeric_value=val,
            unit="ratio",
            reference_range=ref_range,
            flag=flag,
        )
        return AlgorithmResult(lab_value=lv, interpretation_key=interp_key)

    def _indice_mentzer(self, values: list[LabValue], species: str) -> AlgorithmResult | None:
        """Índice de Mentzer = MCV / RBC.

        Requires:
          - MCV: fL
          - RBC: 10^6/uL or 10*6/uL or 10^12/L
        Flag and range sourced from clinical_standards (INDICE_MENTZER).
        """
        mcv = get_validated_value(values, "MCV", ["fL"])
        rbc = get_validated_value(values, "RBC", ["10^6/uL", "10*6/uL", "10^12/L"])

        if mcv is None or rbc is None or rbc == 0:
            return None

        val = round(mcv / rbc, 2)
        flag = self._determine_flag("INDICE_MENTZER", val, species)
        ref_range = self._build_reference_range("INDICE_MENTZER", species)
        interp_key = f"MENTZER_{flag}"

        lv = LabValue(
            parameter_code="INDICE_MENTZER",
            parameter_name_es="Índice de Mentzer",
            raw_value=str(val),
            numeric_value=val,
            unit="ratio",
            reference_range=ref_range,
            flag=flag,
        )
        return AlgorithmResult(lab_value=lv, interpretation_key=interp_key)

    def _calcio_corregido(self, values: list[LabValue], species: str) -> AlgorithmResult | None:
        """Calcio Corregido = Ca + 0.8 * (4.0 - ALB).

        Requires:
          - Ca:  mg/dL
          - ALB: g/dL
        Flag and range sourced from clinical_standards (CALCIO_CORREGIDO).
        """
        ca = get_validated_value(values, "CA", ["mg/dL"])
        alb = get_validated_value(values, "ALB", ["g/dL"])

        if ca is None or alb is None:
            return None

        val = round(ca + 0.8 * (4.0 - alb), 2)
        flag = self._determine_flag("CALCIO_CORREGIDO", val, species)
        ref_range = self._build_reference_range("CALCIO_CORREGIDO", species)

        lv = LabValue(
            parameter_code="CALCIO_CORREGIDO",
            parameter_name_es="Calcio Corregido",
            raw_value=str(val),
            numeric_value=val,
            unit="mg/dL",
            reference_range=ref_range,
            flag=flag,
        )
        return AlgorithmResult(lab_value=lv, interpretation_key="CALCIO_CORREGIDO")
