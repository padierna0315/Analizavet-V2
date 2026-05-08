from clinical_standards import VETERINARY_STANDARDS, STANDARDS_MAPPING
from typing import Dict

SPECIES_MAP: Dict[str, str] = {"Canino": "canine", "Felino": "feline"}

def get_reference_range(parameter_code: str, species: str) -> str:
    """
    Retorna el rango de referencia formateado desde clinical_standards.py.
    Única fuente de verdad para todos los exámenes.
    
    Args:
        parameter_code: código del parámetro (ej: "WBC", "CRE")
        species: especie del paciente en formato DB ("Canino" o "Felino")
    
    Returns:
        String formateado "min - max unidad" o "N/D" si no existe
    """
    species_key = SPECIES_MAP.get(species, "canine") # Default to canine if species not found
    resolved_code = STANDARDS_MAPPING.get(parameter_code, parameter_code)
    param = VETERINARY_STANDARDS.get(resolved_code)
    if not param:
        return "N/D"
    ranges = param.get("ranges", {}).get(species_key, {})
    if not ranges or "min" not in ranges or "max" not in ranges:
        return "N/D"
    unit = param.get("unit", "")
    return f"{ranges['min']} - {ranges['max']} {unit}".strip()
