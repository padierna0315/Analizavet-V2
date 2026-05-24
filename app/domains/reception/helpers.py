def _sanitize_patient_age(has_age: bool, age_value: int | None, age_unit: str | None, age_display: str | None) -> tuple[bool, int | None, str | None, str | None]:
    """Ensure age field consistency. If has_age is False or age_value is None, all fields must be None."""
    if has_age and age_value is not None:
        return has_age, age_value, age_unit, age_display
    return False, None, None, None


# ── AppSheet test_type mapping ─────────────────────────────────────────────────
# Mapeo de Examen_Especifico (AppSheet) → (test_type_display, test_type_code)
# Ordenado de más específico a menos específico para matching exacto.
_APPSHEET_TEST_TYPE_MAP: dict[str, tuple[str, str]] = {
    "Coprologico seriado 3": ("Coprológico Seriado 3", "COPROSC"),
    "Coprologico seriado 2": ("Coprológico Seriado 2", "COPROSC"),
    "Coprologico seriado 1": ("Coprológico Seriado 1", "COPROSC"),
    "Coprologico": ("Coprológico", "COPROSC"),
    "Citoquimico": ("Citoquímico", "CITO"),
    "Perfil Hepatico": ("Perfil Hepático", "CHEM"),
    "Perfil Renal": ("Perfil Renal", "CHEM"),
    "Perfil Basico": ("Perfil Básico", "CHEM"),
}

# Valor por defecto cuando AppSheet no especifica el tipo de examen
_DEFAULT_APPSHEET_TEST_TYPE = ("Química Sanguínea", "CHEM")

# Mapeo de categoría de catálogo → test_type_code (código corto)
_CATEGORY_TO_CODE: dict[str, str] = {
    "Química Sanguínea": "CHEM",
    "Hematología": "CBC",
    "Coprología": "COPROSC",
    "Orina": "URINE",
    "Dermatología": "DERM",
}


def _resolve_appsheet_test_type(examen_especifico: str | None) -> tuple[str, str]:
    """Resuelve Examen_Especifico de AppSheet a (test_type, test_type_code).

    Si el valor no está en el mapa (None o desconocido), retorna el default.
    """
    if not examen_especifico:
        return _DEFAULT_APPSHEET_TEST_TYPE
    return _APPSHEET_TEST_TYPE_MAP.get(examen_especifico.strip(), _DEFAULT_APPSHEET_TEST_TYPE)


def _resolve_test_type_from_exam_types(exam_types: list[str]) -> tuple[str, str] | None:
    """Resolve ExamOrder ``exam_types`` codes to ``(test_type, test_type_code)``.

    Uses the first exam type code to look up the catalog entry.
    Returns ``None`` when the list is empty, so the caller can fall back to
    ``Patient.appsheet_test_type`` for backward compatibility.
    """
    if not exam_types:
        return None

    from app.shared.catalogs.appsheet_exam_catalog import EXAM_CATALOG

    first_code = exam_types[0]
    entry = EXAM_CATALOG.get(first_code)
    if entry:
        category_code = _CATEGORY_TO_CODE.get(entry["category"], "CHEM")
        return (entry["display_name"], category_code)

    return None
