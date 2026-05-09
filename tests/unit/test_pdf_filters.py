import pytest
from markupsafe import Markup
from app.domains.reports.filters import format_ref_range

def test_format_ref_range_with_exponent():
    # Arrange
    ref_str = "5.05 - 16.76 x10^3/µL"
    
    # Act
    result = format_ref_range(ref_str)
    
    # Assert
    assert isinstance(result, Markup)
    # Debe tener el span con la clase y el exponente como <sup>
    assert "5.05" in result
    assert "16.76" in result
    assert "<span class=\"ref-unit\">" in result
    assert "x10<sup>3</sup>" in result
    assert "/µL" in result
    assert result == Markup('<span class="ref-min">5.05</span> - <span class="ref-max">16.76</span> <span class="ref-unit">x10<sup>3</sup>/µL</span>')

def test_format_ref_range_without_exponent():
    ref_str = "131.00 - 205.00 g/L"
    result = format_ref_range(ref_str)
    assert result == Markup('<span class="ref-min">131.00</span> - <span class="ref-max">205.00</span> <span class="ref-unit">g/L</span>')

def test_format_ref_range_no_unit():
    ref_str = "0.0 - 0.0"
    result = format_ref_range(ref_str)
    assert result == Markup('<span class="ref-min">0.0</span> - <span class="ref-max">0.0</span>')

def test_format_ref_range_nd():
    ref_str = "N/D"
    result = format_ref_range(ref_str)
    assert result == Markup("N/D")

def test_format_ref_range_empty():
    assert format_ref_range("") == Markup("")
    assert format_ref_range(None) == Markup("")
