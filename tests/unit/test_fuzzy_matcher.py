"""Tests for fuzzy matcher — normalisation, fuzzy match with accents/typos,
threshold behaviour."""

import pytest

from app.shared.utils.fuzzy_matcher import normalize_text, fuzzy_match


# ── normalize_text ───────────────────────────────────────────────────────


class TestNormalizeText:
    def test_lowercases(self):
        assert normalize_text("HELLO") == "hello"

    def test_strips_accents(self):
        assert normalize_text("Perfil Básico") == "perfil basico"
        assert normalize_text("Uroanálisis") == "uroanalisis"
        assert normalize_text("Coprológico") == "coprologico"

    def test_strips_whitespace(self):
        assert normalize_text("  hello  ") == "hello"
        assert normalize_text("\tspaced\n") == "spaced"

    def test_handles_empty_string(self):
        assert normalize_text("") == ""

    def test_handles_string_with_only_accents(self):
        # é→e, á→a, í→i, ó→o, ú→u
        assert normalize_text("éáíóú") == "eaiou"

    def test_handles_mixed_case_and_accents(self):
        assert normalize_text("Química Sanguínea") == "quimica sanguinea"
        assert normalize_text("Perfil Hepático (PQ2)") == "perfil hepatico (pq2)"


# ── fuzzy_match ──────────────────────────────────────────────────────────


class TestFuzzyMatch:
    def test_exact_match(self):
        result = fuzzy_match("Perfil Básico", ["Perfil Básico", "Hemograma"])
        assert result == "Perfil Básico"

    def test_accent_variation(self):
        """Accented query should still match unaccented candidate or vice versa."""
        result = fuzzy_match("Perfil Basico", ["Perfil Básico", "Hemograma"])
        assert result == "Perfil Básico"

    def test_minor_typo(self):
        result = fuzzy_match("Perfil Basco", ["Perfil Básico", "Hemograma"])
        assert result == "Perfil Básico"

    def test_reordered_words(self):
        """token_sort_ratio handles word reordering."""
        result = fuzzy_match("Sanguínea Química", ["Química Sanguínea"])
        assert result == "Química Sanguínea"

    def test_threshold_below_80(self):
        """Completely unrelated strings should not match."""
        result = fuzzy_match("xyz", ["Perfil Básico", "Hemograma"])
        assert result is None

    def test_partial_word_match_above_threshold(self):
        """Partial but reasonably close should pass threshold."""
        result = fuzzy_match("Hemogram", ["Hemograma", "Perfil Básico"])
        assert result == "Hemograma"

    def test_empty_query_returns_none(self):
        result = fuzzy_match("", ["Perfil Básico", "Hemograma"])
        assert result is None

    def test_empty_candidates_returns_none(self):
        result = fuzzy_match("Perfil Básico", [])
        assert result is None

    def test_both_empty_returns_none(self):
        result = fuzzy_match("", [])
        assert result is None

    def test_with_accents_in_candidates(self):
        """Query without accents matches candidate with accents."""
        result = fuzzy_match("Perfil Hepatico", ["Perfil Hepático", "Hemograma"])
        assert result == "Perfil Hepático"

    def test_returns_best_match(self):
        """When multiple candidates pass, return the highest scorer."""
        result = fuzzy_match("Coprologico Directo", [
            "Coprológico Directo",
            "Coprológico Seriado 2",
            "Hemograma",
        ])
        # "Coprológico Directo" scores 97 vs "Coprológico Seriado 2" at 67
        assert result == "Coprológico Directo"
