"""
Tests for the Algorithm Registry — pure clinical math, no DB.
"""
import pytest
from app.shared.models.lab_value import LabValue
from app.shared.algorithms.registry import AlgorithmRegistry


class MockLabValue:
    """Lightweight mock for unit tests — no SQLModel, no session."""

    def __init__(
        self,
        parameter_code: str,
        numeric_value: float | None,
        unit: str,
        parameter_name_es: str = "",
        raw_value: str = "",
        reference_range: str = "",
        flag: str = "NORMAL",
    ):
        self.parameter_code = parameter_code
        self.parameter_name_es = parameter_name_es or parameter_code
        self.numeric_value = numeric_value
        self.unit = unit
        self.raw_value = raw_value or str(numeric_value) if numeric_value is not None else ""
        self.reference_range = reference_range
        self.flag = flag


def make_lab_values(*tuples: tuple[str, float, str]) -> list[MockLabValue]:
    """Helper: create mock lab values from (code, value, unit) tuples."""
    return [MockLabValue(code, val, unit) for code, val, unit in tuples]


class TestRatioNaK:
    """Ratio Na:K = Na / K. Flag BAJO if < 27."""

    def test_ratio_na_k_normal(self):
        registry = AlgorithmRegistry()
        values = make_lab_values(
            ("NA", 140.0, "mEq/L"),
            ("K", 4.0, "mEq/L"),
        )
        results, errors = registry.run_all(values)

        assert len(errors) == 0
        assert len(results) == 1
        r = results[0]
        assert r.lab_value.parameter_code == "RATIO_NA_K"
        assert r.lab_value.numeric_value == 35.0
        assert r.lab_value.flag == "NORMAL"
        assert r.interpretation_key == "RATIO_NA_K_NORMAL"

    def test_ratio_na_k_bajo(self):
        registry = AlgorithmRegistry()
        values = make_lab_values(
            ("NA", 130.0, "mEq/L"),
            ("K", 6.0, "mEq/L"),
        )
        results, errors = registry.run_all(values)

        assert len(errors) == 0
        r = results[0]
        assert r.lab_value.numeric_value == pytest.approx(21.67, rel=0.01)
        assert r.lab_value.flag == "BAJO"
        assert r.interpretation_key == "RATIO_NA_K_BAJO"

    def test_ratio_na_k_missing_k(self):
        registry = AlgorithmRegistry()
        values = make_lab_values(("NA", 140.0, "mEq/L"),)
        results, errors = registry.run_all(values)

        # No Na:K result — K not present
        ratio_results = [r for r in results if r.lab_value.parameter_code == "RATIO_NA_K"]
        assert len(ratio_results) == 0
        assert len(errors) == 0  # Graceful skip, not an error

    def test_ratio_na_k_wrong_unit_raises(self):
        registry = AlgorithmRegistry()
        values = make_lab_values(
            ("NA", 140.0, "mEq/L"),
            ("K", 4.0, "g/dL"),  # wrong unit
        )
        results, errors = registry.run_all(values)

        ratio_results = [r for r in results if r.lab_value.parameter_code == "RATIO_NA_K"]
        assert len(ratio_results) == 0
        assert len(errors) == 1
        assert "K" in errors[0].reason


class TestRatioBunCre:
    """Ratio BUN/Creatinina = BUN / CRE. Flag ALTO if > 30."""

    def test_ratio_bun_cre_normal(self):
        registry = AlgorithmRegistry()
        values = make_lab_values(
            ("BUN", 30.0, "mg/dL"),
            ("CRE", 1.5, "mg/dL"),
        )
        results, errors = registry.run_all(values)

        assert len(errors) == 0
        r = next(r for r in results if r.lab_value.parameter_code == "RATIO_BUN_CRE")
        assert r.lab_value.numeric_value == 20.0
        assert r.lab_value.flag == "NORMAL"

    def test_ratio_bun_cre_alto(self):
        registry = AlgorithmRegistry()
        values = make_lab_values(
            ("BUN", 90.0, "mg/dL"),
            ("CRE", 2.0, "mg/dL"),
        )
        results, errors = registry.run_all(values)

        r = next(r for r in results if r.lab_value.parameter_code == "RATIO_BUN_CRE")
        assert r.lab_value.numeric_value == 45.0
        assert r.lab_value.flag == "ALTO"
        assert r.interpretation_key == "RATIO_BUN_CRE_ALTO"


class TestIndiceMentzer:
    """Índice de Mentzer = MCV / RBC. Flag BAJO if < 13."""

    def test_mentzer_normal(self):
        registry = AlgorithmRegistry()
        values = make_lab_values(
            ("MCV", 65.0, "fL"),
            ("RBC", 5.0, "10^6/uL"),
        )
        results, errors = registry.run_all(values)

        r = next(r for r in results if r.lab_value.parameter_code == "INDICE_MENTZER")
        assert r.lab_value.numeric_value == 13.0
        assert r.lab_value.flag == "NORMAL"

    def test_mentzer_bajo(self):
        registry = AlgorithmRegistry()
        values = make_lab_values(
            ("MCV", 55.0, "fL"),
            ("RBC", 6.0, "10^6/uL"),
        )
        results, errors = registry.run_all(values)

        r = next(r for r in results if r.lab_value.parameter_code == "INDICE_MENTZER")
        assert r.lab_value.numeric_value == pytest.approx(9.17, rel=0.01)
        assert r.lab_value.flag == "BAJO"
        assert r.interpretation_key == "MENTZER_BAJO"


class TestCalcioCorregido:
    """Calcio Corregido = Ca + 0.8 * (4.0 - ALB)."""

    def test_calcio_corregido_normal_alb_normal(self):
        registry = AlgorithmRegistry()
        values = make_lab_values(
            ("CA", 9.0, "mg/dL"),
            ("ALB", 4.0, "g/dL"),
        )
        results, errors = registry.run_all(values)

        r = next(r for r in results if r.lab_value.parameter_code == "CALCIO_CORREGIDO")
        assert r.lab_value.numeric_value == 9.0
        assert r.lab_value.flag == "NORMAL"

    def test_calcio_corregido_alb_low_raises_calcio(self):
        """Hipoalbuminemia masks true calcemia — corrected value is higher."""
        registry = AlgorithmRegistry()
        values = make_lab_values(
            ("CA", 9.0, "mg/dL"),
            ("ALB", 2.5, "g/dL"),  # Low albumin
        )
        results, errors = registry.run_all(values)

        r = next(r for r in results if r.lab_value.parameter_code == "CALCIO_CORREGIDO")
        # 9.0 + 0.8 * (4.0 - 2.5) = 9.0 + 1.2 = 10.2
        assert r.lab_value.numeric_value == 10.2
        assert r.lab_value.flag == "NORMAL"

    def test_calcio_corregido_missing_alb(self):
        registry = AlgorithmRegistry()
        values = make_lab_values(("CA", 9.0, "mg/dL"),)
        results, errors = registry.run_all(values)

        calcio_results = [r for r in results if r.lab_value.parameter_code == "CALCIO_CORREGIDO"]
        assert len(calcio_results) == 0


class TestAlgorithmRegistryRunAll:
    """run_all() collects results and errors independently."""

    def test_all_four_algorithms_run_when_inputs_present(self):
        registry = AlgorithmRegistry()
        values = make_lab_values(
            ("NA", 140.0, "mEq/L"),
            ("K", 4.0, "mEq/L"),
            ("BUN", 30.0, "mg/dL"),
            ("CRE", 1.5, "mg/dL"),
            ("MCV", 65.0, "fL"),
            ("RBC", 5.0, "10^6/uL"),
            ("CA", 9.0, "mg/dL"),
            ("ALB", 4.0, "g/dL"),
        )
        results, errors = registry.run_all(values)

        assert len(errors) == 0
        assert len(results) == 4
        codes = {r.lab_value.parameter_code for r in results}
        assert codes == {"RATIO_NA_K", "RATIO_BUN_CRE", "INDICE_MENTZER", "CALCIO_CORREGIDO"}

    def test_partial_inputs_skips_what_it_can(self):
        """Only NA and K present → only Ratio Na:K runs."""
        registry = AlgorithmRegistry()
        values = make_lab_values(
            ("NA", 140.0, "mEq/L"),
            ("K", 4.0, "mEq/L"),
        )
        results, errors = registry.run_all(values)

        assert len(results) == 1
        assert results[0].lab_value.parameter_code == "RATIO_NA_K"
        assert len(errors) == 0

    def test_wrong_units_are_reported_as_errors_not_crashes(self):
        registry = AlgorithmRegistry()
        values = make_lab_values(
            ("NA", 140.0, "g/dL"),  # wrong unit
            ("K", 4.0, "mEq/L"),
        )
        results, errors = registry.run_all(values)

        # Ratio Na:K couldn't run due to bad unit → error captured
        ratio_results = [r for r in results if r.lab_value.parameter_code == "RATIO_NA_K"]
        assert len(ratio_results) == 0
        assert len(errors) == 1
        assert "NA" in errors[0].reason
