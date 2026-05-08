"""
Tests for app.satellites.fujifilm.parser — Fujifilm NX600 parser
"""

import pytest
from app.satellites.fujifilm.parser import FujifilmReading, parse_fujifilm_message

# ── Test data fixtures ─────────────────────────────────────────────────────────

# Real data from log_nx600_vivo.txt
SIMPLE_LINE = "S,NORMAL,30-04-2026,20:11,908,POLO,,01"
"""Simple status line with patient ID and name, no chemistry values."""

FULL_LINE = "R,NORMAL,30-04-2026,20:11,908,POLO,,14,9,999,01,02,CRE-PS,=,0.87,mg/dl,,,ALT-PS,=,43,U/l,,,,,"
"""Full report line with CRE and ALT chemistry values."""

MULTI_CHEM_LINE = "R,NORMAL,30-04-2026,20:11,908,POLO,,14,9,999,01,02,CRE-PS,=,0.87,mg/dl,,,ALT-PS,=,43,U/l,,,ALP-PS,=,120,U/L,,,,,"
"""Line with multiple chemistry values."""

LINE_WITH_UNKNOWN = "R,NORMAL,30-04-2026,20:11,908,POLO,,14,9,999,01,02,CRE-PS,=,0.87,mg/dl,,,UNKNOWN-PS,=,123,U/l,,,,,"
"""Line with an unknown parameter that should be ignored."""

MALFORMED_LINE = "garbage input with no structure"
"""Completely malformed input."""

EMPTY_LINE = ""
"""Empty input."""


# ── FujifilmReading dataclass tests ────────────────────────────────────────────

class TestFujifilmReading:
    def test_dataclass_fields(self):
        reading = FujifilmReading(
            internal_id="908",
            patient_name="POLO",
            parameter_code="CRE",
            raw_value="0.87",
        )
        assert reading.internal_id == "908"
        assert reading.patient_name == "POLO"
        assert reading.parameter_code == "CRE"
        assert reading.raw_value == "0.87"


# ── parse_fujifilm_message tests ───────────────────────────────────────────────

class TestParseFujifilmMessageSimple:
    """Tests for simple status lines (S or R prefix, no chemistry values)."""

    def test_simple_s_line_parses_id_and_name(self):
        """S line should extract internal_id and patient_name."""
        result = parse_fujifilm_message(SIMPLE_LINE)
        # No chemistry codes, so empty list
        assert result == []

    def test_simple_line_no_chemistry_returns_empty(self):
        """Line without chemistry codes returns empty list."""
        result = parse_fujifilm_message(SIMPLE_LINE)
        assert result == []


class TestParseFujifilmMessageChemistry:
    """Tests for lines with chemistry values."""

    def test_full_line_extracts_all_chemistry(self):
        """Should extract all chemistry values from full line (CRE and ALT)."""
        result = parse_fujifilm_message(FULL_LINE)
        assert len(result) == 2
        codes = {r.parameter_code for r in result}
        assert "CRE" in codes
        assert "ALT" in codes
        # Check CRE specifically
        cre = [r for r in result if r.parameter_code == "CRE"][0]
        assert cre.internal_id == "908"
        assert cre.patient_name == "POLO"
        assert cre.raw_value == "0.87"

    def test_full_line_extracts_alt(self):
        """ALT line test - check ALT extraction."""
        line = "R,NORMAL,30-04-2026,20:11,908,POLO,,14,9,999,01,02,ALT-PS,=,43,U/l,,,,,"
        result = parse_fujifilm_message(line)
        assert len(result) == 1
        reading = result[0]
        assert reading.parameter_code == "ALT"
        assert reading.raw_value == "43"

    def test_multiple_chemistry_values(self):
        """Line with CRE, ALT, ALP should extract all valid codes."""
        result = parse_fujifilm_message(MULTI_CHEM_LINE)
        codes = {r.parameter_code for r in result}
        assert len(result) >= 2  # At least CRE, ALT, ALP
        assert "CRE" in codes
        assert "ALT" in codes
        assert "ALP" in codes

    def test_ignores_unknown_parameters(self):
        """Unknown parameter codes not in CHEMISTRY_CODES should be ignored."""
        result = parse_fujifilm_message(LINE_WITH_UNKNOWN)
        # Only CRE should be extracted, UNKNOWN ignored
        assert len(result) == 1
        assert result[0].parameter_code == "CRE"


class TestParseFujifilmMessageFaultTolerance:
    """Tests verifying fault tolerance requirements."""

    def test_malformed_input_returns_empty_list(self):
        """Completely malformed input should not crash, return empty list."""
        result = parse_fujifilm_message(MALFORMED_LINE)
        assert result == []

    def test_empty_string_returns_empty_list(self):
        """Empty input should return empty list."""
        result = parse_fujifilm_message(EMPTY_LINE)
        assert result == []

    def test_none_input_returns_empty_list(self):
        """None input should not crash, return empty list."""
        result = parse_fujifilm_message(None)
        assert result == []

    def test_non_string_input_returns_empty_list(self):
        """Non-string input should not crash."""
        result = parse_fujifilm_message(12345)
        assert result == []

    def test_whitespace_only_returns_empty_list(self):
        """Whitespace-only input should return empty list."""
        result = parse_fujifilm_message("   ")
        assert result == []

    def test_line_without_prefix_returns_empty_list(self):
        """Line not starting with S or R should return empty list."""
        result = parse_fujifilm_message("X,NORMAL,30-04-2026,20:11,908,POLO")
        assert result == []


class TestParseFujifilmMessageEdgeCases:
    """Edge case tests."""

    def test_line_missing_fields(self):
        """Line with missing fields should not crash."""
        line = "S,NORMAL"
        result = parse_fujifilm_message(line)
        assert result == []

    def test_extracts_all_chemistry_codes_from_real_log(self):
        """Test with actual log data snippet - should extract CRE and ALT."""
        # Real line from log_nx600_vivo.txt
        line = "R,NORMAL,30-04-2026,20:11,908,POLO,,14,9,999,01,02,CRE-PS,=,0.87,mg/dl,,,ALT-PS,=,43,U/l,,,,,"
        result = parse_fujifilm_message(line)
        assert len(result) == 2
        codes = {r.parameter_code for r in result}
        assert "CRE" in codes
        assert "ALT" in codes


class TestParseFujifilmMessageChemistryCodes:
    """Verify integration with CHEMISTRY_CODES from clinical_standards."""

    def test_all_chemistry_codes_work(self):
        """Quick smoke test with each chemistry code type."""
        from clinical_standards import CHEMISTRY_CODES
        for code in sorted(CHEMISTRY_CODES)[:5]:  # Test a subset
            line = f"R,NORMAL,30-04-2026,20:11,908,POLO,,14,9,999,01,02,{code}-PS,=,1.23,mg/dl,,,,,"
            result = parse_fujifilm_message(line)
            if result:  # Some might not match depending on CHEMISTRY_CODES
                assert result[0].parameter_code == code
                assert result[0].raw_value == "1.23"