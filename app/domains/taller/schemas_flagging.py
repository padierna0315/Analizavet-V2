from pydantic import BaseModel
from typing import Literal

class FlagResult(BaseModel):
    parameter: str
    value: float
    unit: str
    flag: Literal["ALTO", "NORMAL", "BAJO"]
    reference_range: str