from datetime import datetime
from pydantic import BaseModel
from typing import Optional
from app.domains.taller.schemas_flagging import FlagResult


class RawLabValueInput(BaseModel):
    """A single lab value as received from the satellite (before flagging)."""
    parameter_code: str          # "WBC"
    parameter_name_es: str       # "Leucocitos"
    raw_value: str               # "14.26"
    numeric_value: Optional[float] = None
    unit: str                    # "10*9/L"
    reference_range: str         # "5.05-16.76"
    machine_flag: Optional[str] = None   # "N", "H", "L" from OBX


class FlagBatchRequest(BaseModel):
    """Request to flag all lab values for a test result."""
    test_result_id: int
    species: str                 # "Canino", "Felino" — needed for reference ranges
    values: list[RawLabValueInput]


class FlagBatchResult(BaseModel):
    """Result after flagging all values in a test result."""
    test_result_id: int
    flagged_values: list[FlagResult]
    summary: dict                # {"ALTO": 3, "NORMAL": 18, "BAJO": 1}
    status: str                  # "listo" or "error"


# ── Image handling (Phase 8) ──────────────────────────────────────────────────


class ImageUploadItem(BaseModel):
    """Single image to upload — one Base64 image from the Ozelle.

    obs_identifier is the FULL OBX identifier as sent by the Ozelle EHVT-50.
    Confirmed from real HL7 log (log_laboratorio_17 de abril.txt, 119 OBX|ED segments).

    Format: "{BaseCode}_{Type}"
    Examples:
        "WBC_Main"              → Leucocitos_Main.jpg
        "LYM_Part3"             → Linfocitos_Part3.jpg
        "PLT_Histo"             → Plaquetas_Histo.jpg
        "RBC_PLT_Distribution"  → Distribucion_RBC_PLT_Distribution.jpg
        "BACI_Main"             → Bacterias_Main.jpg  (coproscópico)
    """
    obs_identifier: str     # Full OBX identifier: "WBC_Main", "LYM_Part3", etc.
    base64_data: str        # Base64 encoded JPEG (Ozelle sends JPEGs)


class ImageUploadRequest(BaseModel):
    """Batch image upload for a test result."""
    test_result_id: int
    patient_name: str            # "Kitty" — for folder naming
    owner_name: str              # "Laura Cepeda" — for folder naming
    received_at: datetime        # For folder date
    images: list[ImageUploadItem]


class ImageUploadResult(BaseModel):
    """Result after saving images to disk."""
    test_result_id: int
    saved: list[dict]            # [{"parameter_code": "WBC", "parameter_name_es": "Leucocitos", "file_path": "..."}]
    failed: list[dict]           # [{"parameter_code": "X", "error": "..."}]
    total_saved: int
    total_failed: int


class EnrichRequest(BaseModel):
    """Request to create + flag a full test result."""
    patient_id: int
    species: str                     # "Canino" or "Felino"
    test_type: str                   # "Hemograma", "Química Sanguínea", "Coproscópico"
    test_type_code: str              # "CBC", "CHEM", "COPROSC"
    source: str                      # "LIS_OZELLE", "LIS_FILE", etc.
    received_at: datetime
    values: list[RawLabValueInput]