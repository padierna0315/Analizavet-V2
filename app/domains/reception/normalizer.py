import re
from app.domains.reception.schemas import NormalizedPatient, PatientSource


_SPECIES_MAP = {
    "canino": ("Canino", "Macho"),
    "canina": ("Canino", "Hembra"),
    "felino": ("Felino", "Macho"),
    "felina": ("Felino", "Hembra"),
}

_AGE_PATTERN = re.compile(r'^(\d+)(a|m)$', re.IGNORECASE)

# TODO Ruta B: lookup por ID (Registro de Turnos)
# _ID_PATTERN = re.compile(r'^[A-Z]\d+$')


def parse_patient_string(
    raw: str,
    source: PatientSource,
    species_override: str | None = None,
    sex_override: str | None = None,
) -> NormalizedPatient:
    raw = raw.strip()
    if not raw:
        raise ValueError("El string del paciente no puede estar vacío")
    return _parse_from_string(raw, source, species_override, sex_override)


# ── Código patrón: letra mayúscula + 1-2 dígitos (e.g. "A1", "M12") ──
_CODE_PATTERN = re.compile(r'^[A-Z]\d{1,2}$')


def _extract_name_and_code(raw: str) -> tuple[str, str | None]:
    """Extract patient name and optional code prefix.
    
    "LULU"        → ("LULU", None)
    "A1 LULU"     → ("LULU", "A1")
    "M12 rocky"   → ("rocky", "M12")
    """
    tokens = raw.strip().split()
    if len(tokens) >= 2 and _CODE_PATTERN.match(tokens[0]):
        return tokens[1], tokens[0]
    return tokens[0] if tokens else raw, None


def _parse_from_string(
    raw: str,
    source: PatientSource,
    species_override: str | None = None,
    sex_override: str | None = None,
) -> NormalizedPatient:
    # ── CÓDIGO CORTO: si empieza con [LETRA][NÚMERO] es código ──────────
    # No importa la fuente: Ozelle, Fujifilm, lo que sea.
    # El código identifica al paciente, la recepcionista lo bautiza después.
    # Si el parser HL7 extrajo especie/sexo (PID[8]/PID[10]), se usa el override.
    patient_name, code = _extract_name_and_code(raw)
    if code is not None:
        return NormalizedPatient(
            name=patient_name,
            species=species_override or "Desconocida",
            sex=sex_override or "Desconocido",
            has_age=False,
            age_value=None,
            age_unit=None,
            age_display=None,
            owner_name="Sin Tutor",
            source=source,
        )

    # ── FUJIFILM (sin código): solo nombre, sin especie/edad/tutor ─────
    if source == PatientSource.LIS_FUJIFILM:
        return NormalizedPatient(
            name=patient_name,
            species="Desconocida",
            sex="Desconocido",
            has_age=False,
            age_value=None,
            age_unit=None,
            age_display=None,
            owner_name="Sin Tutor",
            source=source,
        )

    tokens = raw.split()

    if len(tokens) < 2:
        raise ValueError("Formato inválido. Mínimo: nombre especie")

    name = tokens[0].capitalize()
    species_token = tokens[1].lower()

    if species_token not in _SPECIES_MAP:
        raise ValueError(
            f"Especie no reconocida: {species_token}. Use: canino, canina, felino, felina"
        )

    species, sex = _SPECIES_MAP[species_token]

    age_match = _AGE_PATTERN.match(tokens[2]) if len(tokens) > 2 else None

    if age_match:
        age_value = int(age_match.group(1))
        age_letter = age_match.group(2).lower()
        if age_letter == 'a':
            age_unit = "años"
            age_display = f"{age_value} año" if age_value == 1 else f"{age_value} años"
        else:
            age_unit = "meses"
            age_display = f"{age_value} mes" if age_value == 1 else f"{age_value} meses"
        owner_tokens = tokens[3:]
        has_age = True
    else:
        age_value = None
        age_unit = None
        age_display = None
        owner_tokens = tokens[2:]
        has_age = False

    if not owner_tokens:
        owner_name = "Sin Tutor"
    else:
        owner_name = " ".join(t.capitalize() for t in owner_tokens)

    return NormalizedPatient(
        name=name,
        species=species,
        sex=sex,
        has_age=has_age,
        age_value=age_value,
        age_unit=age_unit,
        age_display=age_display,
        owner_name=owner_name,
        source=source,
    )