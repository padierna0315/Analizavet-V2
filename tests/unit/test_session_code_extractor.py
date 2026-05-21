r"""Tests for SessionCodeExtractor — pure function, no DB dependencies."""

import pytest
from app.services.session_code_extractor import SessionCodeExtractor


# ── Parametrized: all spec scenarios ──────────────────────────────────────

@pytest.mark.parametrize(
    "input_str, expected",
    [
        # Happy path — space-separated
        ("M5 KIARA", "M5"),
        # No space — concatenated
        ("M5KIARA", "M5"),
        # Hyphen-separated
        ("M5-KIARA", "M5"),
        # Multi-digit code
        ("A105 BUDDY", "A105"),
        # Single letter + single digit
        ("F2", "F2"),
        # With leading/trailing whitespace
        ("  M5 KIARA  ", "M5"),
        # ── Rejected — no code ──
        ("KIARA", None),
        ("", None),
        ("   ", None),
        # Rejected — digits first (malformed)
        ("5M KIARA", None),
        # Rejected — lowercase letter
        ("m5 KIARA", None),
        # Rejected — only digits
        ("123", None),
    ],
)
def test_extract_parametrized(input_str, expected):
    """extract() returns code prefix or None matching ^[A-Z]\d+ at start."""
    result = SessionCodeExtractor.extract(input_str)
    assert result == expected


# ── Edge cases beyond the spec ─────────────────────────────────────────────

def test_extract_with_newline_prefix():
    """Whitespace-insensitive extraction still works with \n."""
    result = SessionCodeExtractor.extract("\nM5 KIARA")
    assert result == "M5"


def test_extract_with_tab_prefix():
    """Tab-separated code still extracted."""
    result = SessionCodeExtractor.extract("\tM5\tKIARA")
    assert result == "M5"


def test_extract_single_letter_number_only():
    """String that IS just a code returns the code itself."""
    result = SessionCodeExtractor.extract("Z99")
    assert result == "Z99"


def test_extract_returns_none_for_none_input():
    """None input gracefully returns None (defensive, annotated as str-only)."""
    result = SessionCodeExtractor.extract(None)
    assert result is None
