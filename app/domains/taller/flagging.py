import logfire
from app.domains.taller.schemas_flagging import FlagResult
from app.shared.clinical_standards import evaluate_flag, get_species_key

class ClinicalFlaggingService:

    def flag_value(self, parameter: str, value: float, unit: str, species: str) -> FlagResult:
        # Validate species: must be recognized (in SPECIES_MAP) or "Desconocida"
        species_key = get_species_key(species)
        if species_key is None and species != "Desconocida":
            raise ValueError(f"Especie desconocida: {species}")

        result = evaluate_flag(parameter, value, species)

        # Preserve warnings for missing parameter/ranges (spec requires warning parity)
        if result["reference_range"] == "":
            logfire.warning(f"Parameter {parameter} not found in standards or no reference range for {species}")

        return FlagResult(
            parameter=parameter,
            value=value,
            unit=unit,
            flag=result["flag"],
            reference_range=result["reference_range"],
        )

    def flag_batch(self, values: list[dict], species: str) -> list[FlagResult]:
        return [self.flag_value(**item, species=species) for item in values]
