"""Text normalisation and fuzzy matching utilities.

Used to match user-provided exam names (with possible typos, accents,
and formatting differences) against the canonical catalog.
"""

import unicodedata
from typing import List, Optional

from thefuzz import fuzz


def normalize_text(text: str) -> str:
    """Strip accents, lowercase, and strip surrounding whitespace.

    Uses NFKD decomposition so that combined characters (é → e + ́) are
    decomposed and the combining marks are then removed.

    Examples:
        >>> normalize_text("Perfil Básico")
        'perfil basico'
        >>> normalize_text("  Uroanálisis  ")
        'uroanalisis'
    """
    text = text.lower().strip()
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def fuzzy_match(query: str, candidates: List[str]) -> Optional[str]:
    """Return the best-matching candidate string, or ``None``.

    Uses ``thefuzz.token_sort_ratio`` which tokenises both strings and
    compares the sorted tokens — this handles word re-ordering well.

    Threshold: **≥ 80** (thefuzz scale is 0–100).

    Examples:
        >>> fuzzy_match("Perfil Basico", ["Perfil Básico", "Hemograma"])
        'Perfil Básico'
        >>> fuzzy_match("xyz", ["Perfil Básico", "Hemograma"])
        None
    """
    if not query or not candidates:
        return None

    best_score = 0
    best_match: Optional[str] = None

    for candidate in candidates:
        score = fuzz.token_sort_ratio(query, candidate)
        if score > best_score:
            best_score = score
            best_match = candidate

    if best_score >= 80:
        return best_match
    return None
