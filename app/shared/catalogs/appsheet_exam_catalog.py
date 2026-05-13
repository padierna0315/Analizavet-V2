"""Catalog of exam types and their aliases as they appear in AppSheet.

Each entry maps an internal code to its display name, category, and known
aliases (variations extracted from AppSheet data over time).  Lookup is
case-insensitive and accent-insensitive.

Usage:
    >>> from app.shared.catalogs.appsheet_exam_catalog import lookup_exam
    >>> lookup_exam("PQ1")
    {'code': 'CHEM_BASIC', 'display_name': 'Perfil Básico', ...}
    >>> lookup_exam("Perfil Hepático")
    {'code': 'CHEM_HEPATIC', 'display_name': 'Perfil Hepático', ...}
    >>> lookup_exam("Unknown")
    None
"""

from typing import Optional, Dict
import unicodedata


# ── Catalog ──────────────────────────────────────────────────────────────

EXAM_CATALOG: Dict[str, Dict] = {
    "CHEM_BASIC": {
        "display_name": "Perfil Básico",
        "category": "Química Sanguínea",
        "aliases": [
            "Perfil Basico",
            "Perfil Básico",
            "PQ1",
            "Química Básica",
            "Quimica Basica",
            "Bioquímica Básica",
            "Bioquimica Basica",
            "Perfil Basico (PQ1)",
            "Perfil Básico (PQ1)",
        ],
    },
    "CHEM_HEPATIC": {
        "display_name": "Perfil Hepático",
        "category": "Química Sanguínea",
        "aliases": [
            "Perfil Hepatico",
            "Perfil Hepático",
            "PQ2",
            "Química Hepática",
            "Quimica Hepatica",
            "Perfil Hepatico (PQ2)",
            "Perfil Hepático (PQ2)",
        ],
    },
    "CHEM_RENAL": {
        "display_name": "Perfil Renal",
        "category": "Química Sanguínea",
        "aliases": [
            "Perfil Renal",
            "PQ3",
            "Química Renal",
            "Quimica Renal",
            "Perfil Renal (PQ3)",
        ],
    },
    "CBC": {
        "display_name": "Hemograma",
        "category": "Hematología",
        "aliases": [
            "Hemograma",
            "Biometría Hemática",
            "Biometria Hematica",
            "BH",
            "Citología Hemática",
            "Citologia Hematica",
            "Hemograma Completo",
            "CBC",
        ],
    },
    "COPROSC_SINGLE": {
        "display_name": "Coprológico Directo",
        "category": "Coprología",
        "aliases": [
            "Coprológico",
            "Coprologico",
            "Coproscópico",
            "Coproscopico",
            "Examen Copro",
            "Copro directo",
            "Coprologico Directo",
            "Coprológico Directo",
        ],
    },
    "COPROSC_SERIADO_2": {
        "display_name": "Coprológico Seriado 2",
        "category": "Coprología",
        "aliases": [
            "Coprologico Seriado 2",
            "Coprológico Seriado 2",
            "Seriado 2",
            "Coproscópico Seriado 2",
            "Coproscopico Seriado 2",
            "Copro Seriado 2",
            "Coprologico Seriado 2 muestras",
            "Coprológico Seriado 2 muestras",
        ],
    },
    "COPROSC_SERIADO_3": {
        "display_name": "Coprológico Seriado 3",
        "category": "Coprología",
        "aliases": [
            "Coprologico Seriado 3",
            "Coprológico Seriado 3",
            "Seriado 3",
            "Coproscópico Seriado 3",
            "Coproscopico Seriado 3",
            "Copro Seriado 3",
            "Coprologico Seriado 3 muestras",
            "Coprológico Seriado 3 muestras",
        ],
    },
    "SKIN_SCRAPE": {
        "display_name": "Raspado Cutáneo",
        "category": "Dermatología",
        "aliases": [
            "Raspado Cutáneo",
            "Raspado Cutaneo",
            "Skin Scrape",
            "Dermatoscopia",
            "Raspado de Piel",
        ],
    },
    "URINALYSIS": {
        "display_name": "Uroanálisis",
        "category": "Orina",
        "aliases": [
            "Uroanálisis",
            "Uroanalisis",
            "Orina",
            "Examen de Orina",
            "Parcial de Orina",
            "Urocultivo",
        ],
    },
}


# ── Normalization helpers ────────────────────────────────────────────────


def _normalize(text: str) -> str:
    """Lowercase + strip accents for lookup purposes."""
    text = text.lower().strip()
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


# Pre-build a normalized alias → code map once at module load.
_ALIAS_MAP: Dict[str, str] = {}
for _code, _entry in EXAM_CATALOG.items():
    for _alias in _entry["aliases"]:
        _ALIAS_MAP[_normalize(_alias)] = _code


# ── Public API ───────────────────────────────────────────────────────────


def lookup_exam(query: str) -> Optional[Dict]:
    """Look up an exam by code, alias, or display name.

    Returns the full catalog entry dict (with ``code`` injected) or ``None``
    when nothing matches.

    The lookup is case-insensitive and accent-insensitive.
    """
    normalized = _normalize(query)

    # 1. Exact code match (case-insensitive)
    for code, entry in EXAM_CATALOG.items():
        if code.lower() == normalized:
            return {"code": code, **entry}

    # 2. Alias match
    matched_code = _ALIAS_MAP.get(normalized)
    if matched_code is not None:
        return {"code": matched_code, **EXAM_CATALOG[matched_code]}

    return None
