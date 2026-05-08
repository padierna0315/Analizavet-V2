from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship

if TYPE_CHECKING:
    from app.shared.models.test_result import TestResult


class LabValue(SQLModel, table=True):
    """One lab parameter value from a test result.
    
    Example: WBC = 14.26 10*9/L → NORMAL (for Canino, range 5.05-16.76)
    
    Design decision: flag is a COLUMN here (not a separate table).
    99% of queries need the flag immediately with the value.
    """
    __tablename__ = "labvalue"

    id: Optional[int] = Field(default=None, primary_key=True)

    # Link to test result
    test_result_id: int = Field(foreign_key="testresult.id", index=True)

    # Parameter info
    parameter_code: str         # Machine code: "WBC", "RBC", "PLT"
    parameter_name_es: str      # Spanish name: "Leucocitos", "Eritrocitos", "Plaquetas"

    # Value
    raw_value: str              # Exact string from machine: "14.26"
    numeric_value: Optional[float] = Field(default=None)  # None if non-numeric
    unit: str                   # "10*9/L", "%", "g/dL"

    # Reference range (from machine)
    reference_range: str        # "5.05-16.76"

    # Clinical flag — THE key field
    flag: str = Field(default="NORMAL")  # "ALTO", "NORMAL", "BAJO"

    # Machine flag (what the machine said, before our own calculation)
    machine_flag: Optional[str] = Field(default=None)  # "H", "L", "N" from OBX

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Relationship
    test_result: Optional["TestResult"] = Relationship(back_populates="lab_values")