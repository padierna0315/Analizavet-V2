from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING
from sqlmodel import SQLModel, Field, Relationship

if TYPE_CHECKING:
    from app.shared.models.test_result import TestResult


class PatientImage(SQLModel, table=True):
    """A histogram image from the Ozelle machine.
    
    Images stored as FILES on disk (not in DB).
    DB stores the path + metadata only.
    
    File structure on disk:
        images/{PatientName}_{OwnerName}/{YYYYMMDD}/{ParameterNameEs}.png
    
    Example:
        images/Kitty_LauraCepeda/20260424/Leucocitos.png
    """
    __tablename__ = "patientimage"

    id: Optional[int] = Field(default=None, primary_key=True)

    # Link to test result
    test_result_id: int = Field(foreign_key="testresult.id", index=True)

    # Parameter identification
    parameter_code: str         # Machine code: "WBC"
    parameter_name_es: str      # Spanish name: "Leucocitos"

    # File storage
    file_path: str              # Full path: "images/Kitty_LauraCepeda/20260424/Leucocitos.png"
    patient_folder: str         # "images/Kitty_LauraCepeda/20260424/"

    # Image metadata
    image_type: str = Field(default="histogram")
    file_size_bytes: Optional[int] = Field(default=None)

    # Triage control — visibility in PDF report
    is_included_in_report: bool = Field(default=True)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Relationship
    test_result: Optional["TestResult"] = Relationship(back_populates="images")