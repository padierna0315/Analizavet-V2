from pydantic import BaseModel, field_validator, model_validator
from datetime import datetime, timezone
from typing import Literal, Optional
from enum import Enum


class PatientSource(str, Enum):
    LIS_OZELLE = "LIS_OZELLE"       # TCP automático, puerto 6000
    LIS_FILE = "LIS_FILE"           # .txt subido manualmente (mismo formato Ozelle)
    LIS_FUJIFILM = "LIS_FUJIFILM"   # TCP automático, puerto 6001 (futuro)
    MANUAL = "MANUAL"               # Formulario manual en pantalla
    APPSHEET = "APPSHEET"           # Sincronización desde Google AppSheet


class RawPatientInput(BaseModel):
    """Raw string exactly as it comes from the satellite.
    Example: 'kitty felina 2a Laura Cepeda'
    """
    raw_string: str
    session_code: Optional[str] = None # New optional field
    source: PatientSource
    received_at: datetime  # UTC
    species_override: Optional[str] = None  # Explicit species from HL7 parser (e.g. "Felino", "Canino")
    sex_override: Optional[str] = None      # Explicit sex from HL7 parser (e.g. "Hembra", "Macho")

    @field_validator('raw_string')
    @classmethod
    def strip_and_validate(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("raw_string cannot be empty")
        return v


class NormalizedPatient(BaseModel):
    """Patient data after normalization. Ready for Taller.
    All fields in natural Spanish — no codes, no abbreviations.
    
    Fujifilm source may produce "Desconocida" / "Desconocido" 
    when the machine only sends the patient name.
    """
    name: str                                    # "Kitty"
    species: Literal["Canino", "Felino", "Desconocida"]
    sex: Literal["Macho", "Hembra", "Desconocido"]
    has_age: bool                                # False for coproscopics
    age_value: int | None                        # 2
    age_unit: Literal["meses", "años"] | None    # "años"
    age_display: str | None                      # "2 años" or None
    owner_name: str                              # "Laura Cepeda"
    source: PatientSource

    @field_validator('name')
    @classmethod
    def capitalize_name(cls, v: str) -> str:
        return v.capitalize()

    @field_validator('owner_name')
    @classmethod
    def capitalize_owner_name(cls, v: str) -> str:
        return v.title()

    @model_validator(mode='after')
    def check_age_consistency(self) -> 'NormalizedPatient':
        if self.has_age:
            if self.age_value is None or self.age_unit is None or self.age_display is None:
                raise ValueError("When has_age is True, age_value, age_unit, and age_display must be set")
        else:
            if self.age_value is not None or self.age_unit is not None or self.age_display is not None:
                raise ValueError("When has_age is False, age_value, age_unit, and age_display must be None")
        return self


class BaulResult(BaseModel):
    """Result of registering a patient in the Baúl."""
    patient_id: int
    created: bool      # True = new patient, False = already existed
    patient: "NormalizedPatient"  # The normalized data (from input)
