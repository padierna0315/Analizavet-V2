from typing import Optional
from sqlmodel import SQLModel, Field

class Doctor(SQLModel, table=True):
    __tablename__ = "doctor"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    specialty: Optional[str] = Field(default=None)
