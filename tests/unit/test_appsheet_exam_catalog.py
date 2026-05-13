"""Tests for exam catalog lookup — exact match, alias match, unknown code."""

import pytest

from app.shared.catalogs.appsheet_exam_catalog import (
    lookup_exam,
    EXAM_CATALOG,
)


class TestLookupExact:
    """Lookup by canonical code."""

    def test_exact_code_chem_basic(self):
        result = lookup_exam("CHEM_BASIC")
        assert result is not None
        assert result["code"] == "CHEM_BASIC"
        assert result["display_name"] == "Perfil Básico"

    def test_exact_code_cbc(self):
        result = lookup_exam("CBC")
        assert result is not None
        assert result["code"] == "CBC"

    def test_exact_code_urinalysis(self):
        result = lookup_exam("URINALYSIS")
        assert result is not None
        assert result["code"] == "URINALYSIS"

    def test_exact_code_skin_scrape(self):
        result = lookup_exam("SKIN_SCRAPE")
        assert result is not None
        assert result["code"] == "SKIN_SCRAPE"

    def test_all_catalog_entries_have_required_fields(self):
        for code, entry in EXAM_CATALOG.items():
            assert "display_name" in entry, f"{code} missing display_name"
            assert "category" in entry, f"{code} missing category"
            assert "aliases" in entry, f"{code} missing aliases"
            assert isinstance(entry["aliases"], list), f"{code} aliases not a list"
            assert len(entry["aliases"]) > 0, f"{code} has no aliases"


class TestLookupAlias:
    """Lookup by alias (including accented and unaccented variants)."""

    @pytest.mark.parametrize(
        "alias, expected_code",
        [
            ("Perfil Basico", "CHEM_BASIC"),
            ("Perfil Básico", "CHEM_BASIC"),
            ("PQ1", "CHEM_BASIC"),
            ("Química Básica", "CHEM_BASIC"),
            ("Quimica Basica", "CHEM_BASIC"),
            ("Perfil Hepatico", "CHEM_HEPATIC"),
            ("Perfil Hepático", "CHEM_HEPATIC"),
            ("PQ2", "CHEM_HEPATIC"),
            ("PQ3", "CHEM_RENAL"),
            ("Perfil Renal", "CHEM_RENAL"),
            ("Hemograma", "CBC"),
            ("Biometría Hemática", "CBC"),
            ("Biometria Hematica", "CBC"),
            ("BH", "CBC"),
            ("Coprológico", "COPROSC_SINGLE"),
            ("Coprologico", "COPROSC_SINGLE"),
            ("Coproscópico", "COPROSC_SINGLE"),
            ("Seriado 2", "COPROSC_SERIADO_2"),
            ("Coprologico Seriado 2", "COPROSC_SERIADO_2"),
            ("Coprológico Seriado 3", "COPROSC_SERIADO_3"),
            ("Seriado 3", "COPROSC_SERIADO_3"),
            ("Raspado Cutáneo", "SKIN_SCRAPE"),
            ("Raspado Cutaneo", "SKIN_SCRAPE"),
            ("Skin Scrape", "SKIN_SCRAPE"),
            ("Uroanálisis", "URINALYSIS"),
            ("Uroanalisis", "URINALYSIS"),
            ("Orina", "URINALYSIS"),
            ("Examen de Orina", "URINALYSIS"),
        ],
    )
    def test_alias_resolves_to_correct_code(self, alias, expected_code):
        result = lookup_exam(alias)
        assert result is not None, f"Alias '{alias}' should resolve to {expected_code}"
        assert result["code"] == expected_code, (
            f"Alias '{alias}' resolved to {result['code']}, expected {expected_code}"
        )

    def test_alias_with_parentheses(self):
        """Aliases that contain parenthetical notes like 'Perfil Básico (PQ1)'."""
        result = lookup_exam("Perfil Básico (PQ1)")
        assert result is not None
        assert result["code"] == "CHEM_BASIC"

    def test_alias_case_insensitive(self):
        result = lookup_exam("perfil basico")
        assert result is not None
        assert result["code"] == "CHEM_BASIC"

        result = lookup_exam("PERFIL BÁSICO")
        assert result is not None
        assert result["code"] == "CHEM_BASIC"


class TestLookupUnknown:
    """Lookup with unrecognised input returns None."""

    @pytest.mark.parametrize(
        "query",
        [
            "",
            "   ",
            "NonExistentExam",
            "XYZ123",
            "Random String That Doesn't Match",
        ],
    )
    def test_unknown_returns_none(self, query):
        assert lookup_exam(query) is None
