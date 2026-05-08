from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING, List
import json
from sqlmodel import SQLModel, Field, Relationship, Column
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator
from sqlalchemy.ext.mutable import MutableList

if TYPE_CHECKING:
    from app.shared.models.test_result import TestResult


class _JsonListType(TypeDecorator):
    """
    Polymorphic JSON list type.

    - PostgreSQL: delegates to native JSONB for full operator support.
    - SQLite (tests): uses TEXT with manual json.dumps / json.loads.
    """
    impl = String
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import JSONB
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(String())

    def process_bind_param(self, value, dialect):
        if value is None:
            return "[]"
        if dialect.name == "postgresql":
            # asyncpg returns / accepts Python lists natively
            return value if isinstance(value, list) else json.loads(value)
        # SQLite — always serialize to JSON string
        return json.dumps(value if isinstance(value, list) else json.loads(value))

    def process_result_value(self, value, dialect):
        if value is None:
            return []
        if isinstance(value, list):
            return value  # PostgreSQL driver already parsed it
        try:
            result = json.loads(value)
            return result if isinstance(result, list) else []
        except (json.JSONDecodeError, TypeError):
            return []


class _TrackedList(MutableList):
    """
    MutableList subclass with a coerce() that transparently handles:
    - list   → wrap as-is (normal flow)
    - str    → parse JSON first, then wrap (SQLite returns raw JSON strings)
    - None   → return empty list
    """
    @classmethod
    def coerce(cls, key, value):
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        if isinstance(value, list):
            return cls(value)
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return cls(parsed if isinstance(parsed, list) else [])
            except (json.JSONDecodeError, TypeError):
                return cls()
        return super().coerce(key, value)


# Associate the tracked list with the polymorphic JSON type.
_MutableJsonList = _TrackedList.as_mutable(_JsonListType)



class Patient(SQLModel, table=True):
    """The Baúl — every patient registered in the system.
    
    Deduplication key: normalized_name + normalized_owner + species
    (stored as lowercase, accent-stripped for comparison)
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    
    # Display fields (naturalized, capitalized)
    name: str                   # "Kitty"
    species: str                # "Canino" or "Felino"
    sex: str                    # "Macho" or "Hembra"
    owner_name: str             # "Laura Cepeda"
    breed: Optional[str] = Field(default="Mestizo")
    
    # Age fields (None for coproscopics)
    has_age: bool = Field(default=True)
    age_value: Optional[int] = Field(default=None)
    age_unit: Optional[str] = Field(default=None)   # "años" or "meses"
    age_display: Optional[str] = Field(default=None) # "2 años"
    
    # Source tracking
    source: str                 # PatientSource value as string
    
    # Waiting room fields (for sala-espera-persistente)
    session_code: Optional[str] = Field(default=None, index=True)  # e.g., "A1-20260501"
    waiting_room_status: str = Field(default="active")  # active, deleted, pdf_generated
    sources_received: List[str] = Field(
        default_factory=list,
        sa_column=Column(_MutableJsonList),
    )  # Track which sources have provided data (Ozelle, Fujifilm, JSON)

    
    # Deduplication keys (normalized: lowercase + no accents)
    # These are used for comparison only — never displayed
    normalized_name: str = Field(index=True)
    normalized_owner: str = Field(index=True)
    
    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Relationships
    test_results: list["TestResult"] = Relationship(
        back_populates="patient",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
