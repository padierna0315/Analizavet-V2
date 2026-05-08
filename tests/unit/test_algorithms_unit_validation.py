"""
Tests for the unit validation module.
Santiago's rule: strict unit validation before clinical math operations.
"""
import pytest
from app.shared.models.lab_value import LabValue
from app.shared.algorithms.unit_validation import get_validated_value


class MockLabValue:
    """Lightweight mock for unit tests — no DB, no SQLModel."""

    def __init__(self, parameter_code: str, numeric_value: float | None, unit: str):
        self.parameter_code = parameter_code
        self.numeric_value = numeric_value
        self.unit = unit


class TestGetValidatedValue:
    """Unit validation — strict unit checking before returning a value."""

    def test_returns_value_when_parameter_and_unit_match(self):
        values = [
            MockLabValue("NA", 140.0, "mEq/L"),
            MockLabValue("K", 4.5, "mEq/L"),
        ]
        result = get_validated_value(values, "NA", ["mEq/L"])
        assert result == 140.0

    def test_returns_value_case_insensitive_unit(self):
        values = [MockLabValue("NA", 140.0, "MEQ/L")]
        result = get_validated_value(values, "NA", ["mEq/L"])
        assert result == 140.0

    def test_returns_value_with_spaces_in_unit(self):
        values = [MockLabValue("NA", 140.0, " mEq/L ")]
        result = get_validated_value(values, "NA", ["mEq/L"])
        assert result == 140.0

    def test_returns_none_when_parameter_not_found(self):
        values = [MockLabValue("NA", 140.0, "mEq/L")]
        result = get_validated_value(values, "K", ["mEq/L"])
        assert result is None

    def test_returns_none_when_numeric_value_is_null(self):
        values = [MockLabValue("NA", None, "mEq/L")]
        result = get_validated_value(values, "NA", ["mEq/L"])
        assert result is None

    def test_raises_when_unit_does_not_match(self):
        values = [MockLabValue("NA", 140.0, "mmol/L")]
        with pytest.raises(ValueError, match="Unidad incorrecta para NA"):
            get_validated_value(values, "NA", ["mEq/L"])

    def test_raises_with_expected_and_received_units_in_error(self):
        values = [MockLabValue("NA", 140.0, "g/dL")]
        with pytest.raises(ValueError, match="Esperada:") as exc_info:
            get_validated_value(values, "NA", ["mEq/L", "mmol/L"])
        assert "mEq/L" in str(exc_info.value)
        assert "mmol/L" in str(exc_info.value)
        assert "g/dL" in str(exc_info.value)

    def test_multiple_expected_units_any_match_returns_value(self):
        values = [MockLabValue("NA", 140.0, "mmol/L")]
        result = get_validated_value(values, "NA", ["mEq/L", "mmol/L"])
        assert result == 140.0

    def test_none_numeric_value_returns_none_without_unit_check(self):
        """If numeric_value is None, we skip unit check and return None."""
        values = [MockLabValue("NA", None, "mEq/L")]
        result = get_validated_value(values, "NA", ["mEq/L"])
        assert result is None
