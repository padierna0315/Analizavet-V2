"""Tests for canonical flag evaluation functions in clinical_standards.

Covers: SPECIES_MAP, get_species_key(), get_reference_range(), evaluate_flag().
"""
import pytest
from clinical_standards import (
    SPECIES_MAP,
    get_species_key,
    get_reference_range,
    evaluate_flag,
)


# ── SPECIES_MAP ─────────────────────────────────────────────────────────────

def test_species_map_contains_canine_mappings():
    """SPECIES_MAP must map Canino/Canina → canine."""
    assert "Canino" in SPECIES_MAP
    assert SPECIES_MAP["Canino"] == "canine"
    assert "Canina" in SPECIES_MAP
    assert SPECIES_MAP["Canina"] == "canine"


def test_species_map_contains_feline_mappings():
    """SPECIES_MAP must map Felino/Felina → feline."""
    assert "Felino" in SPECIES_MAP
    assert SPECIES_MAP["Felino"] == "feline"
    assert "Felina" in SPECIES_MAP
    assert SPECIES_MAP["Felina"] == "feline"


# ── get_species_key() ───────────────────────────────────────────────────────

def test_get_species_key_canine():
    """Canino/Canina must return 'canine'."""
    assert get_species_key("Canino") == "canine"
    assert get_species_key("Canina") == "canine"


def test_get_species_key_feline():
    """Felino/Felina must return 'feline'."""
    assert get_species_key("Felino") == "feline"
    assert get_species_key("Felina") == "feline"


def test_get_species_key_desconocida():
    """'Desconocida' must return None."""
    assert get_species_key("Desconocida") is None


def test_get_species_key_unknown():
    """Unrecognized species (e.g., 'Equino') must return None."""
    assert get_species_key("Equino") is None
    assert get_species_key("Ave") is None
    assert get_species_key("") is None


# ── get_reference_range() ───────────────────────────────────────────────────

def test_get_reference_range_canine_wbc():
    """Canine WBC must return the correctly formatted range."""
    result = get_reference_range("WBC", "Canino")
    assert result == "5.05 - 16.76 x10^3/µL"


def test_get_reference_range_feline_wbc():
    """Feline WBC must return the correctly formatted range."""
    result = get_reference_range("WBC", "Felino")
    assert result == "2.8 - 17.0 x10^3/µL"


def test_get_reference_range_alias_ret():
    """RET alias must resolve to RET# and return its canine range."""
    result = get_reference_range("RET", "Canino")
    assert result == "3.0 - 110.0 x10^3/µL"


def test_get_reference_range_unknown_code():
    """Unknown parameter code must return 'N/D'."""
    result = get_reference_range("UNKNOWN", "Canino")
    assert result == "N/D"


def test_get_reference_range_desconocida():
    """'Desconocida' species must return 'N/D'."""
    result = get_reference_range("WBC", "Desconocida")
    assert result == "N/D"


def test_get_reference_range_no_range_for_species():
    """Parameter with None range for a species must return 'N/D'.
    e.g., cT4 only has canine range, feline is None.
    """
    result = get_reference_range("cT4", "Felino")
    assert result == "N/D"


# ── evaluate_flag() ─────────────────────────────────────────────────────────

def test_evaluate_flag_normal():
    """Value within range must return NORMAL with formatted reference_range."""
    result = evaluate_flag("HCT", 45.0, "Canino")
    assert result["flag"] == "NORMAL"
    assert result["reference_range"] == "37.3 - 61.7 %"


def test_evaluate_flag_alto():
    """Value above max must return ALTO."""
    result = evaluate_flag("RBC", 13.0, "Felino")
    assert result["flag"] == "ALTO"
    assert result["reference_range"] == "6.54 - 12.2 x10^6/µL"


def test_evaluate_flag_bajo():
    """Value below min must return BAJO."""
    result = evaluate_flag("WBC", 3.0, "Canino")
    assert result["flag"] == "BAJO"
    assert result["reference_range"] == "5.05 - 16.76 x10^3/µL"


def test_evaluate_flag_desconocida():
    """'Desconocida' species must return NORMAL with 'N/D' range."""
    result = evaluate_flag("RBC", 6.0, "Desconocida")
    assert result["flag"] == "NORMAL"
    assert result["reference_range"] == "N/D"


def test_evaluate_flag_missing_parameter():
    """Unknown parameter must return NORMAL with empty reference_range."""
    result = evaluate_flag("UNKNOWN", 10.0, "Canino")
    assert result["flag"] == "NORMAL"
    assert result["reference_range"] == ""


def test_evaluate_flag_unknown_species():
    """Unrecognized species (e.g., 'Equino') must return NORMAL with 'N/D'."""
    result = evaluate_flag("RBC", 6.0, "Equino")
    assert result["flag"] == "NORMAL"
    assert result["reference_range"] == "N/D"


def test_evaluate_flag_alias_neu():
    """NEU alias must resolve to NEU# and evaluate correctly (normal)."""
    result = evaluate_flag("NEU", 5.0, "Canino")
    assert result["flag"] == "NORMAL"
    assert result["reference_range"] == "2.95 - 11.64 x10^3/µL"


def test_evaluate_flag_exact_boundary_min():
    """Value exactly at the minimum boundary must be NORMAL."""
    result = evaluate_flag("WBC", 5.05, "Canino")
    assert result["flag"] == "NORMAL"
    assert result["reference_range"] == "5.05 - 16.76 x10^3/µL"


def test_evaluate_flag_exact_boundary_max():
    """Value exactly at the maximum boundary must be NORMAL."""
    result = evaluate_flag("WBC", 16.76, "Canino")
    assert result["flag"] == "NORMAL"
    assert result["reference_range"] == "5.05 - 16.76 x10^3/µL"


def test_evaluate_flag_returns_only_two_keys():
    """evaluate_flag must return exactly two keys: flag and reference_range."""
    result = evaluate_flag("WBC", 10.0, "Canino")
    assert set(result.keys()) == {"flag", "reference_range"}
