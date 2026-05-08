import pytest
from app.domains.taller.flagging import ClinicalFlaggingService

service = ClinicalFlaggingService()

def test_normal_value_canino():
    result = service.flag_value("RBC", 6.0, "x10^6/µL", "Canino")
    assert result.flag == "NORMAL"
    assert "5.65-8.87" in result.reference_range

def test_high_value_canino():
    result = service.flag_value("RBC", 9.0, "x10^6/µL", "Canino")
    assert result.flag == "ALTO"

def test_low_value_canino():
    result = service.flag_value("RBC", 4.0, "x10^6/µL", "Canino")
    assert result.flag == "BAJO"

def test_normal_value_felino():
    result = service.flag_value("RBC", 7.0, "x10^6/µL", "Felino")
    assert result.flag == "NORMAL"
    assert "6.54-12.2" in result.reference_range

def test_unknown_parameter_returns_normal():
    result = service.flag_value("UNKNOWN", 10.0, "units", "Canino")
    assert result.flag == "NORMAL"
    assert result.reference_range == ""

def test_unknown_species_raises():
    with pytest.raises(ValueError, match="Especie desconocida: Equino"):
        service.flag_value("RBC", 6.0, "x10^6/µL", "Equino")

def test_flag_batch():
    batch = [
        {"parameter": "RBC", "value": 6.0, "unit": "x10^6/µL"},
        {"parameter": "WBC", "value": 15.0, "unit": "x10^3/µL"}
    ]
    results = service.flag_batch(batch, "Canino")
    assert len(results) == 2
    assert results[0].flag == "NORMAL"


def test_alias_ret_resolves_to_ret_hash():
    """RET should resolve to RET# and use its reference range."""
    result = service.flag_value("RET", 50.0, "x10^3/µL", "Canino")
    assert result.flag == "NORMAL"
    assert "3.0-110.0" in result.reference_range


def test_alias_neu_resolves_to_neu_hash():
    """NEU should resolve to NEU# and use its reference range."""
    result = service.flag_value("NEU", 5.0, "x10^3/µL", "Canino")
    assert result.flag == "NORMAL"
    assert "2.95-11.64" in result.reference_range


def test_alias_lym_resolves_to_lym_hash():
    """LYM should resolve to LYM# and use its reference range."""
    result = service.flag_value("LYM", 5.0, "x10^3/µL", "Felino")
    assert result.flag == "NORMAL"
    assert "0.92-6.88" in result.reference_range


def test_alias_neu_high_flagged_correctly():
    """NEU alias should flag as ALTO when value exceeds NEU# range."""
    result = service.flag_value("NEU", 15.0, "x10^3/µL", "Canino")
    assert result.flag == "ALTO"


def test_alias_lym_low_flagged_correctly():
    """LYM alias should flag as BAJO when value below LYM# range."""
    result = service.flag_value("LYM", 0.5, "x10^3/µL", "Felino")
    assert result.flag == "BAJO"