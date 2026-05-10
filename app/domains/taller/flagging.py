import logfire
from app.domains.taller.schemas_flagging import FlagResult
from clinical_standards import VETERINARY_STANDARDS, STANDARDS_MAPPING

class ClinicalFlaggingService:
    SPECIES_MAP = {
        "Canino": "canine",
        "Canina": "canine",
        "Felino": "feline",
        "Felina": "feline"
    }

    def _get_species_key(self, species: str) -> str | None:
        if species == "Desconocida":
            return None
        if species not in self.SPECIES_MAP:
            raise ValueError(f"Especie desconocida: {species}")
        return self.SPECIES_MAP[species]

    def flag_value(self, parameter: str, value: float, unit: str, species: str) -> FlagResult:
        species_key = self._get_species_key(species)
        
        if species_key is None:
            # No se puede evaluar flag sin especie conocida — NORMAL por defecto
            return FlagResult(
                parameter=parameter,
                value=value,
                unit=unit,
                flag="NORMAL",
                reference_range="N/D"
            )

        resolved_parameter = STANDARDS_MAPPING.get(parameter, parameter)
        param_data = VETERINARY_STANDARDS.get(resolved_parameter)
        if not param_data:
            logfire.warning(f"Parameter {parameter} not found in standards")
            return FlagResult(
                parameter=parameter,
                value=value,
                unit=unit,
                flag="NORMAL",
                reference_range=""
            )

        ranges = param_data["ranges"].get(species_key)
        if not ranges:
            logfire.warning(f"No reference range for {parameter} in {species}")
            return FlagResult(
                parameter=parameter,
                value=value,
                unit=unit,
                flag="NORMAL",
                reference_range=""
            )

        min_val = ranges["min"]
        max_val = ranges["max"]
        reference_range = f"{min_val}-{max_val} {param_data['unit']}"

        if value < min_val:
            flag = "BAJO"
        elif value > max_val:
            flag = "ALTO"
        else:
            flag = "NORMAL"

        return FlagResult(
            parameter=parameter,
            value=value,
            unit=unit,
            flag=flag,
            reference_range=reference_range
        )

    def flag_batch(self, values: list[dict], species: str) -> list[FlagResult]:
        return [self.flag_value(**item, species=species) for item in values]
