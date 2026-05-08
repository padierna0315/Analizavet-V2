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


def parse_patient_string(raw: str, source: PatientSource) -> NormalizedPatient:
    raw = raw.strip()
    if not raw:
        raise ValueError("El string del paciente no puede estar vacío")
    return _parse_from_string(raw, source)


def _parse_from_string(raw: str, source: PatientSource) -> NormalizedPatient:
    tokens = raw.split()

    if len(tokens) < 3:
        raise ValueError("Formato inválido. Mínimo: nombre especie [edad] tutor")

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
        raise ValueError("Formato inválido. Mínimo: nombre especie [edad] tutor")

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