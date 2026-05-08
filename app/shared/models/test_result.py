from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship

if TYPE_CHECKING:
    from app.domains.patients.models import Patient
    from app.shared.models.lab_value import LabValue
    from app.shared.models.patient_image import PatientImage


class TestResult(SQLModel, table=True):
    """One lab test run for one patient.
    
    A single Ozelle message = one TestResult.
    Contains all the LabValues and Images from that run.
    """
    __tablename__ = "testresult"

    id: Optional[int] = Field(default=None, primary_key=True)

    # Link to patient
    patient_id: int = Field(foreign_key="patient.id", index=True)

    # Test metadata
    test_type: str              # "Hemograma", "Química Sanguínea", "Coproscópico"
    test_type_code: str         # "CBC", "CHEM", "COPROSC" (original machine code)
    source: str                 # "LIS_OZELLE", "LIS_FILE", etc.

    # Status
    status: str = Field(default="pendiente")
    # pendiente → procesando → listo → error

    # Summary flags (computed after flagging)
    flag_alto_count: int = Field(default=0)
    flag_normal_count: int = Field(default=0)
    flag_bajo_count: int = Field(default=0)

    # Timestamps
    received_at: datetime       # when the machine sent it
    processed_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


    # Metadata del médico (todos los tipos de examen)
    doctor_name: Optional[str] = Field(default=None)

    # Metadata coprológico
    copro_color: Optional[str] = Field(default=None)
    copro_consistencia: Optional[str] = Field(default=None)
    copro_olor: Optional[str] = Field(default=None)
    copro_moco: Optional[bool] = Field(default=None)

    # Metadata citoquímico  
    cito_color: Optional[str] = Field(default=None)
    cito_turbidez: Optional[str] = Field(default=None)
    cito_aspecto: Optional[str] = Field(default=None)

    # Relationships
    patient: Optional["Patient"] = Relationship(back_populates="test_results")
    lab_values: list["LabValue"] = Relationship(
        back_populates="test_result",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    images: list["PatientImage"] = Relationship(
        back_populates="test_result",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )