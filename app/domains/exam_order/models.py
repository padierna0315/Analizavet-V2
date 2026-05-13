from datetime import datetime
from typing import TYPE_CHECKING, Optional, List
from sqlmodel import SQLModel, Field, Column, Relationship

from app.domains.patients.models import _MutableJsonList

if TYPE_CHECKING:
    from app.domains.patients.models import Patient


class ExamOrder(SQLModel, table=True):
    """Orden de examen para un paciente, sincronizada desde AppSheet.

    Cada fila en AppSheet (tabla Solicitudes) genera un ExamOrder que
    especifica qué tipo(s) de examen deben realizarse para el paciente.
    """

    id: Optional[int] = Field(default=None, primary_key=True)

    # Link to patient
    patient_id: int = Field(foreign_key="patient.id", index=True)

    # Session / waiting-room identifier
    session_code: str = Field(index=True)

    # Which exam types were requested (stored as JSON list)
    exam_types: List[str] = Field(
        default_factory=list,
        sa_column=Column(_MutableJsonList),
    )

    # Exam lifecycle: pending, partial, complete, cancelled
    status: str = Field(default="pending")

    # AppSheet row ID for sync tracking
    appsheet_row_id: Optional[str] = Field(default=None)

    # Relationships
    patient: Optional["Patient"] = Relationship(back_populates="exam_orders")

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
