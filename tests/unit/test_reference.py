"""
Tests for app.core.reference — alias resolution
"""
import pytest
from app.core.reference import get_reference_range


def test_get_reference_range_alias_ret_canino():
    """RET should resolve to RET# and return canine reference range."""
    result = get_reference_range("RET", "Canino")
    assert result == "3.0 - 110.0 x10^3/µL"


def test_get_reference_range_alias_neu_canino():
    """NEU should resolve to NEU# and return canine reference range."""
    result = get_reference_range("NEU", "Canino")
    assert result == "2.95 - 11.64 x10^3/µL"


def test_get_reference_range_alias_lym_felino():
    """LYM should resolve to LYM# and return feline reference range."""
    result = get_reference_range("LYM", "Felino")
    assert result == "0.92 - 6.88 x10^3/µL"


def test_get_reference_range_unknown_code():
    """Unknown parameter code should return 'N/D'."""
    result = get_reference_range("UNKNOWN", "Canino")
    assert result == "N/D"


def test_get_reference_range_direct_code_still_works():
    """Direct codes (without alias) should still work."""
    result = get_reference_range("WBC", "Canino")
    assert result == "5.05 - 16.76 x10^3/µL"


def test_get_reference_range_felino_species():
    """Direct code with Felino species should return correct range."""
    result = get_reference_range("WBC", "Felino")
    assert result == "2.8 - 17.0 x10^3/µL"
