"""
Unit Validation — strict unit checking before clinical math.

Santiago's rule: NO clinical math operations without validating units first.
This prevents garbage-in-garbage-out errors in algorithm calculations.
"""
from app.shared.models.lab_value import LabValue
from typing import Optional


def get_validated_value(
    values: list[LabValue],
    parameter_code: str,
    expected_units: list[str],
) -> Optional[float]:
    """Finds a parameter and STRICTLY validates its unit before returning the numeric value.

    Args:
        values: List of LabValue objects from a test result.
        parameter_code: The parameter code to look for (e.g. "NA", "K", "BUN").
        expected_units: List of acceptable unit strings (case-insensitive, spaces stripped).
                       e.g. ["mEq/L", "mmol/L"]

    Returns:
        The numeric_value if found AND unit matches.

    Raises:
        ValueError: If parameter is found but unit does NOT match expected.
    """
    for lv in values:
        if lv.parameter_code == parameter_code:
            if lv.numeric_value is None:
                return None
            # Strict unit check (case insensitive, strip spaces)
            safe_unit = lv.unit.strip().lower()
            safe_expected = [u.strip().lower() for u in expected_units]
            if safe_unit not in safe_expected:
                raise ValueError(
                    f"Unidad incorrecta para {parameter_code}. "
                    f"Esperada: {expected_units}, Recibida: {lv.unit}"
                )
            return lv.numeric_value
    return None
