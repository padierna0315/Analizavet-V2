"""Router for ExamOrder API — webhook, CRUD, and status management."""

from typing import List, Optional

import logfire
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.domains.exam_order.schemas import ExamOrderResponse
from app.domains.exam_order.service import ExamOrderService

router = APIRouter(tags=["Exam Orders"])
_service = ExamOrderService()


# ── Webhook schemas ───────────────────────────────────────────────────────


class AppSheetWebhookRow(BaseModel):
    """Single row from an AppSheet webhook payload.

    Fields match the AppSheet table columns using aliases for the
    Spanish column names sent by the AppSheet integration.
    """

    Codigo_Corto: str = ""
    Examen_Especifico: str = ""
    Paciente_ID: Optional[str] = None
    Row_ID: Optional[str] = None

    model_config = {"extra": "ignore", "populate_by_name": True}


class AppSheetWebhookPayload(BaseModel):
    """Webhook payload — a list of row mutations."""

    rows: List[AppSheetWebhookRow]


class AppSheetWebhookResponse(BaseModel):
    """Summary response from the webhook endpoint."""

    created: int = 0
    updated: int = 0
    errors: int = 0


# ── Status update schema ──────────────────────────────────────────────────


class StatusUpdateRequest(BaseModel):
    """Request body for updating an ExamOrder's status."""

    status: str


# ── Endpoints ─────────────────────────────────────────────────────────────


@router.post("/api/appsheet/webhook", response_model=AppSheetWebhookResponse)
async def appsheet_webhook(
    payload: List[AppSheetWebhookRow],
    session: AsyncSession = Depends(get_session),
):
    """Receive AppSheet row mutations and create/update ExamOrders.

    Accepts a list of AppSheet row dicts. Each row is processed
    independently — errors in one row don't affect others.
    Returns a summary with created/updated/error counts.
    """
    result = AppSheetWebhookResponse()

    for row in payload:
        try:
            row_dict = row.model_dump(exclude_unset=False, by_alias=True)
            # Convert to the format the service expects
            data = {
                "Codigo_Corto": row.Codigo_Corto or "",
                "Examen_Especifico": row.Examen_Especifico or "",
            }
            if row.Paciente_ID:
                data["Paciente_ID"] = row.Paciente_ID
            if row.Row_ID:
                data["appsheet_row_id"] = row.Row_ID

            if not data.get("Codigo_Corto"):
                logfire.warning("AppSheet webhook row missing Codigo_Corto — skipping")
                result.errors += 1
                continue

            existing = await _service.get_by_session_code(data["Codigo_Corto"], session)
            await _service.create_from_appsheet(data, session)
            if existing:
                result.updated += 1
            else:
                result.created += 1

        except Exception as e:
            logfire.error(f"Error processing AppSheet webhook row: {e}")
            result.errors += 1

    logfire.info(
        f"AppSheet webhook processed: "
        f"{result.created} created, {result.updated} updated, {result.errors} errors"
    )
    return result


@router.get(
    "/exam-orders/patient/{patient_id}",
    response_model=List[ExamOrderResponse],
)
async def get_exam_orders_by_patient(
    patient_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Return all ExamOrders for a given patient, newest first."""
    orders = await _service.get_by_patient(patient_id, session)
    return [ExamOrderResponse.model_validate(o) for o in orders]


@router.get(
    "/exam-orders/session/{session_code}",
    response_model=ExamOrderResponse,
)
async def get_exam_order_by_session_code(
    session_code: str,
    session: AsyncSession = Depends(get_session),
):
    """Return a single ExamOrder by its session code."""
    order = await _service.get_by_session_code(session_code, session)
    if order is None:
        raise HTTPException(
            status_code=404,
            detail=f"ExamOrder with session_code '{session_code}' not found",
        )
    return ExamOrderResponse.model_validate(order)


@router.patch(
    "/exam-orders/{order_id}/status",
    response_model=ExamOrderResponse,
)
async def update_exam_order_status(
    order_id: int,
    body: StatusUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    """Update the status of an ExamOrder, validating the transition.

    Valid transitions:
      - pending  → partial | complete | cancelled
      - partial  → complete | cancelled
      - complete/cancelled are terminal (no transitions out)
    """
    try:
        order = await _service.update_status(order_id, body.status, session)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ExamOrderResponse.model_validate(order)
