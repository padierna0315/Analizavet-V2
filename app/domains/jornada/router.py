"""Jornada router — daily session summary endpoint."""

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.domains.jornada.service import (
    read_session_start,
    get_session_results,
    format_report,
)

router = APIRouter(prefix="/jornada", tags=["Jornada"])


@router.get("/resumen")
async def jornada_resumen(
    session: AsyncSession = Depends(get_session),
):
    """Return a summary of today's test results since session start.

    The session start is determined by a marker file written by iniciar.sh.
    Returns a plain text report grouped by test category.
    """
    session_start = read_session_start()
    if session_start is None:
        return Response(
            content="No hay sesión activa. Inicie el sistema con iniciar.sh.",
            media_type="text/plain; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="resumen-jornada.txt"'
            },
        )

    grouped = await get_session_results(session_start, session)
    report = format_report(grouped)

    return Response(
        content=report,
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="resumen-jornada.txt"'
        },
    )
