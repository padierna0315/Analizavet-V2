"""
Interpretations Dictionary — "Archivero Temporal".

Santiago's rule: explanatory texts do NOT live in the database.
They live here as a pure Python dictionary, decoupled from persistence.

The PDF generator reads this dictionary at render time.
If Santiago wants to change a word tomorrow, he changes the code — no DB migration.
"""
from typing import TypedDict


class InterpretationEntry(TypedDict):
    """One interpretation entry in the dictionary."""
    text_es: str
    severity: str  # "info" | "warning" | "critical"


INTERPRETATIONS: dict[str, InterpretationEntry] = {
    # ── Ratio Na:K ────────────────────────────────────────────────────────────
    "RATIO_NA_K_BAJO": {
        "text_es": (
            "Cocientes inferiores a 27:1 sugieren hipoadrenocorticismo o "
            "seudohiperkalemia. Inferiores a 20:1 indican crisis addisoniana inminente."
        ),
        "severity": "critical",
    },
    "RATIO_NA_K_NORMAL": {
        "text_es": "Ratio Na:K dentro del rango esperado (27:1 - 40:1).",
        "severity": "info",
    },
    # ── Ratio BUN/Creatinina ─────────────────────────────────────────────────
    "RATIO_BUN_CRE_ALTO": {
        "text_es": (
            "Ratios superiores a 30:1 con densidad urinaria alta sugieren "
            "azotemia prerrenal (deshidratación). Si la densidad es baja, "
            "evaluar daño estructural."
        ),
        "severity": "warning",
    },
    "RATIO_BUN_CRE_NORMAL": {
        "text_es": "Ratio BUN/Creatinina dentro del rango esperado (≤30:1).",
        "severity": "info",
    },
    # ── Índice de Mentzer ────────────────────────────────────────────────────
    "MENTZER_BAJO": {
        "text_es": (
            "Índice de Mentzer < 13 sugiere deficiencia de hierro crónica. "
            "> 13 sugiere disfunción primaria de síntesis de globinas."
        ),
        "severity": "warning",
    },
    "MENTZER_NORMAL": {
        "text_es": "Índice de Mentzer dentro del rango esperado (≥13).",
        "severity": "info",
    },
    # ── Calcio Corregido ─────────────────────────────────────────────────────
    "CALCIO_CORREGIDO": {
        "text_es": (
            "Calcio corregido por hipoalbuminemia. Evita diagnósticos errados "
            "de hipocalcemia."
        ),
        "severity": "info",
    },
}


def get_interpretation(key: str) -> InterpretationEntry | None:
    """Look up an interpretation by its key."""
    return INTERPRETATIONS.get(key)
