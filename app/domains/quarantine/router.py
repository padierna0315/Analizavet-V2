"""Quarantine review router — admin review of rejected lab data.

HTMX endpoints for listing, force-matching, discarding, and counting
quarantined items from the isolation gatekeeper.
"""

from datetime import datetime, timezone

import logfire
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, select

from app.database import get_session
from app.services.session_code_extractor import SessionCodeExtractor
from app.shared.models.data_quarantine import DataQuarantine, QuarantineStatus

router = APIRouter(prefix="/quarantine", tags=["Quarantine"])
templates = Jinja2Templates(directory="app/templates")


# ── List pending items ─────────────────────────────────────────────────────


@router.get("", response_class=HTMLResponse)
async def list_quarantine(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Return HTMX page listing all pending quarantined items."""
    stmt = (
        select(DataQuarantine)
        .where(DataQuarantine.status == QuarantineStatus.PENDING.value)
        .order_by(DataQuarantine.created_at.desc())
    )
    result = await session.execute(stmt)
    items = result.scalars().all()

    return templates.TemplateResponse(
        request,
        "quarantine/list.html",
        {"items": items},
    )


# ── Force-match: admin assigns session code ─────────────────────────────────


@router.post("/{quarantine_id}/force-match", response_class=HTMLResponse)
async def force_match(
    request: Request,
    quarantine_id: int,
    session_code: str = Form(...),
    session: AsyncSession = Depends(get_session),
):
    """Force-match a quarantined item by assigning a session code.

    Validates the entered code with SessionCodeExtractor before applying.
    """
    # Validate session code format
    extracted = SessionCodeExtractor.extract(session_code)
    if extracted is None:
        raise HTTPException(
            status_code=400,
            detail="Código de sesión inválido. Debe comenzar con una letra mayúscula seguida de dígitos (ej: M5).",
        )

    # Fetch quarantine record
    quarantine = await session.get(DataQuarantine, quarantine_id)
    if quarantine is None:
        raise HTTPException(status_code=404, detail="Ítem no encontrado")

    if quarantine.status != QuarantineStatus.PENDING.value:
        raise HTTPException(
            status_code=409,
            detail="Este ítem ya fue procesado. Solo se pueden forzar ítems pendientes.",
        )

    # Apply force-match
    quarantine.status = QuarantineStatus.FORCED.value
    quarantine.session_code = extracted
    quarantine.processed_at = datetime.now(timezone.utc)
    session.add(quarantine)
    await session.commit()

    logfire.info(f"Quarantine {quarantine_id}: force-matched with code {extracted}")

    # Return OOB swap: remove the row + update the counter badge
    pending_count = await _pending_count(session)

    return HTMLResponse(
        content=f"""<div id="quarantine-row-{quarantine_id}" hx-swap-oob="delete"></div>
<div id="quarantine-badge" hx-swap-oob="innerHTML">{_badge_html(pending_count)}</div>"""
    )


# ── Review modal ─────────────────────────────────────────────────────────────


@router.get("/{quarantine_id}/review-modal", response_class=HTMLResponse)
async def review_modal(
    request: Request,
    quarantine_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Return HTMX modal with force-match form for a quarantine item."""
    quarantine = await session.get(DataQuarantine, quarantine_id)
    if quarantine is None:
        raise HTTPException(status_code=404, detail="Ítem no encontrado")

    return templates.TemplateResponse(
        request,
        "quarantine/review_modal.html",
        {"item": quarantine},
    )


# ── Discard: soft-delete item ───────────────────────────────────────────────


@router.post("/{quarantine_id}/discard", response_class=HTMLResponse)
async def discard_item(
    request: Request,
    quarantine_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Soft-delete a quarantined item by setting status to 'discarded'."""
    quarantine = await session.get(DataQuarantine, quarantine_id)
    if quarantine is None:
        raise HTTPException(status_code=404, detail="Ítem no encontrado")

    quarantine.status = QuarantineStatus.DISCARDED.value
    quarantine.processed_at = datetime.now(timezone.utc)
    session.add(quarantine)
    await session.commit()

    logfire.info(f"Quarantine {quarantine_id}: discarded")

    # Return OOB swap: remove the row + update the counter badge
    pending_count = await _pending_count(session)

    return HTMLResponse(
        content=f"""<div id="quarantine-row-{quarantine_id}" hx-swap-oob="delete"></div>
<div id="quarantine-badge" hx-swap-oob="innerHTML">{_badge_html(pending_count)}</div>"""
    )


# ── Count badge ─────────────────────────────────────────────────────────────


@router.get("/count", response_class=HTMLResponse)
async def quarantine_count(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Return badge HTML with pending quarantine item count."""
    count = await _pending_count(session)
    return HTMLResponse(content=_badge_html(count))


# ── Helpers ─────────────────────────────────────────────────────────────────


async def _pending_count(session: AsyncSession) -> int:
    """Return the number of pending quarantine items."""
    stmt = select(func.count(DataQuarantine.id)).where(
        DataQuarantine.status == QuarantineStatus.PENDING.value
    )
    result = await session.execute(stmt)
    return result.scalar() or 0


def _badge_html(count: int) -> str:
    """Render the quarantine badge element with inline styles."""
    if count == 0:
        return ""
    return (
        f'<a href="/quarantine" '
        f'title="{count} elemento(s) en cuarentena" '
        f'style="color: #fbbf24; text-decoration: none; font-weight: bold; '
        f'padding: 0.35rem 0.75rem; background: rgba(251,191,36,0.15); '
        f'border-radius: 4px; font-size: 0.85rem; display: inline-flex; '
        f'align-items: center; gap: 0.3rem;">'
        f"⚠ {count}</a>"
    )
