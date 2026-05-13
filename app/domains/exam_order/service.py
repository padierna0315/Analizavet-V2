"""Service for creating and managing ExamOrder records from AppSheet data."""

from datetime import datetime
from typing import Dict, List, Optional

import logfire
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.domains.exam_order.models import ExamOrder
from app.domains.exam_order.schemas import ExamTypeInfo
from app.shared.catalogs.appsheet_exam_catalog import EXAM_CATALOG, lookup_exam
from app.shared.utils.fuzzy_matcher import fuzzy_match


# ── Valid status transitions ─────────────────────────────────────────────

_VALID_TRANSITIONS: Dict[str, set[str]] = {
    "pending": {"partial", "complete", "cancelled"},
    "partial": {"complete", "cancelled"},
    # "complete" and "cancelled" are terminal — no transitions out.
}


def _validate_transition(current: str, new: str) -> None:
    """Raise ``ValueError`` if the status transition is not allowed."""
    allowed = _VALID_TRANSITIONS.get(current)
    if allowed is None:
        raise ValueError(
            f"Status '{current}' is terminal — cannot transition to '{new}'"
        )
    if new not in allowed:
        raise ValueError(
            f"Invalid transition: '{current}' → '{new}'. "
            f"Allowed from '{current}': {', '.join(sorted(allowed))}"
        )


def _build_alias_list() -> List[str]:
    """Build a flat list of all known aliases from the catalog (no dedup needed)."""
    aliases: List[str] = []
    for entry in EXAM_CATALOG.values():
        aliases.extend(entry["aliases"])
    return aliases


# Pre-build once at module load.
_ALL_ALIASES = _build_alias_list()


# ── Service class ────────────────────────────────────────────────────────


class ExamOrderService:
    """Manages ExamOrder lifecycle — creation from AppSheet, lookup, status transitions."""

    # ── Public API ────────────────────────────────────────────────────────

    async def create_from_appsheet(
        self, data: dict, session: AsyncSession
    ) -> ExamOrder:
        """Create or update an ExamOrder from a raw AppSheet row dict.

        Idempotent by ``session_code``: if an order already exists for the
        given *Codigo_Corto* it is updated rather than duplicated.
        """
        session_code = (data.get("Codigo_Corto") or "").strip()
        if not session_code:
            raise ValueError("AppSheet row is missing Codigo_Corto")

        raw_exam = (data.get("Examen_Especifico") or "").strip()

        exam_types = await self.resolve_exam_types(raw_exam)

        # Look for existing order by session_code
        existing = await self.get_by_session_code(session_code, session)

        if existing is not None:
            # Update existing
            existing.exam_types = exam_types
            existing.updated_at = datetime.now()
            if existing.status == "pending":
                existing.status = "pending"

            appsheet_row_id = data.get("appsheet_row_id") or data.get("Row ID")
            if appsheet_row_id:
                existing.appsheet_row_id = appsheet_row_id

            session.add(existing)
            await session.commit()
            await session.refresh(existing)
            logfire.info(
                f"Updated ExamOrder {existing.id} for session {session_code}"
            )
            return existing

        # Create new
        appsheet_row_id = data.get("appsheet_row_id") or data.get("Row ID")
        patient_id = data.get("patient_id") or data.get("Paciente_ID")

        if patient_id is None:
            raise ValueError("AppSheet row is missing patient identifier")

        order = ExamOrder(
            patient_id=int(patient_id),
            session_code=session_code,
            exam_types=exam_types,
            status="pending",
            appsheet_row_id=appsheet_row_id,
        )
        session.add(order)
        await session.commit()
        await session.refresh(order)
        logfire.info(
            f"Created ExamOrder {order.id} for session {session_code} "
            f"with {len(exam_types)} exam type(s)"
        )
        return order

    async def resolve_exam_types(
        self, raw_exam_string: str
    ) -> List[str]:
        """Split a raw AppSheet exam string and return resolved canonical codes.

        Resolution strategy for each part:
        1. Exact catalog lookup (code or alias, case/accent-insensitive)
        2. Fuzzy match against all known aliases (threshold ≥80)
        3. If no match, log a warning and skip

        Returns a list of canonical codes (e.g. ``["CHEM_BASIC", "CBC"]``).
        """
        if not raw_exam_string.strip():
            return []

        parts = [p.strip() for p in raw_exam_string.split(",")]
        resolved: List[str] = []

        for part in parts:
            if not part:
                continue

            # 1. Exact / alias lookup
            entry = lookup_exam(part)
            if entry is not None:
                resolved.append(entry["code"])
                continue

            # 2. Fuzzy fallback
            matched_alias = fuzzy_match(part, _ALL_ALIASES)
            if matched_alias is not None:
                entry = lookup_exam(matched_alias)
                if entry is not None:
                    logfire.info(
                        f"Fuzzy matched '{part}' → '{matched_alias}' "
                        f"({entry['code']})"
                    )
                    resolved.append(entry["code"])
                    continue

            # 3. Unmapped
            logfire.warning(
                f"Could not resolve exam type '{part}' — skipping"
            )

        return resolved

    async def get_by_patient(
        self, patient_id: int, session: AsyncSession
    ) -> List[ExamOrder]:
        """Return all ExamOrders for a given patient."""
        stmt = (
            select(ExamOrder)
            .where(ExamOrder.patient_id == patient_id)
            .order_by(ExamOrder.created_at.desc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_session_code(
        self, session_code: str, session: AsyncSession
    ) -> Optional[ExamOrder]:
        """Return a single ExamOrder by its session code, or ``None``."""
        stmt = select(ExamOrder).where(ExamOrder.session_code == session_code)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_status(
        self, order_id: int, new_status: str, session: AsyncSession
    ) -> ExamOrder:
        """Update the status of an ExamOrder, validating the transition.

        Raises ``ValueError`` on invalid transitions.
        """
        order = await session.get(ExamOrder, order_id)
        if order is None:
            raise ValueError(f"ExamOrder with id={order_id} not found")

        _validate_transition(order.status, new_status)

        order.status = new_status
        order.updated_at = datetime.now()
        session.add(order)
        await session.commit()
        await session.refresh(order)

        logfire.info(
            f"ExamOrder {order.id} status: {order.status} → {new_status}"
        )
        return order
