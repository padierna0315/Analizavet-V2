from datetime import datetime, timezone
from typing import Optional
from sqlmodel import SQLModel, Field


class PatientRegistry(SQLModel, table=True):
    """RESERVED — Future Turno system.
    
    When the turn generator tool is built, this table will store
    pre-registered patients with short IDs (G2, A1, etc.).
    
    The Recepción normalizer will have a Ruta B:
    if input matches ID pattern (e.g. "G2") → lookup here instead of parsing string.
    
    Currently empty. Do NOT use in production yet.
    """
    __tablename__ = "patientregistry"

    id: Optional[int] = Field(default=None, primary_key=True)

    # Short ID assigned by the turn generator tool
    turno_id: str = Field(unique=True, index=True)  # "G2", "A1", "B15"

    # Full patient data (pre-registered)
    name: str
    species: str            # "Canino" or "Felino"
    sex: str                # "Macho" or "Hembra"
    age_display: Optional[str] = Field(default=None)
    owner_name: str

    # Optional medical context
    profile: Optional[str] = Field(default=None)    # "renal/hepatico/tiroideo"
    doctor_name: Optional[str] = Field(default=None) # "Giovanni"

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    active: bool = Field(default=True)