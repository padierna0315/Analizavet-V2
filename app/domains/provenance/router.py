"""Provenance router — Raw data view for patient audit trail."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.database import get_session
from app.shared.models.raw_data_log import RawDataLog
from app.template_engine import templates

router = APIRouter(tags=["Provenance"])


@router.get("/patients/{patient_id}/raw-data", response_class=HTMLResponse)
async def patient_raw_data_view(
    request: Request,
    patient_id: int,
    session: AsyncSession = Depends(get_session),
):
    """HTMX partial: returns raw data provenance for a patient.

    Fetches all RawDataLog rows for the given patient_id and renders
    them as source-grouped cards with scrollable preformatted blocks.
    """
    try:
        stmt = (
            select(RawDataLog)
            .where(RawDataLog.patient_id == patient_id)
            .order_by(RawDataLog.received_at.desc())
        )
        result = await session.execute(stmt)
        logs = result.scalars().all()
    except Exception:
        logs = []

    logs_as_dicts = []
    for log in logs:
        logs_as_dicts.append({
            "id": log.id,
            "source": log.source,
            "raw_data": log.raw_data,
            "received_at": log.received_at.isoformat() if log.received_at else None,
            "captured_at": log.captured_at.isoformat() if log.captured_at else None,
            "processed_at": log.processed_at.isoformat() if log.processed_at else None,
            "session_code": log.session_code,
            "status": log.status,
        })

    template = templates.env.get_template("provenance/raw_data_view.html")
    html = template.render(
        request=request,
        patient_id=patient_id,
        logs=logs_as_dicts,
    )
    return HTMLResponse(content=html)
