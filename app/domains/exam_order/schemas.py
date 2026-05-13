"""Pydantic schemas for ExamOrder — create, response, and resolved exam types."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, field_validator


class ExamTypeInfo(BaseModel):
    """Resolved exam type with canonical code, display name, and category."""

    code: str
    display_name: str
    category: str


class ExamOrderCreate(BaseModel):
    """Schema for creating an ExamOrder from AppSheet webhook data."""

    patient_id: int
    session_code: str
    exam_types: List[str]
    appsheet_row_id: Optional[str] = None
    status: str = "pending"

    @field_validator("session_code")
    @classmethod
    def session_code_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("session_code cannot be empty")
        return v.strip()

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        allowed = {"pending", "partial", "complete", "cancelled"}
        if v not in allowed:
            raise ValueError(f"status must be one of {allowed}")
        return v


class ExamOrderResponse(BaseModel):
    """Schema for API responses containing ExamOrder data."""

    id: int
    patient_id: int
    session_code: str
    exam_types: List[str]
    status: str
    appsheet_row_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
