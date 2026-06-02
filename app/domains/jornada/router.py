"""Jornada router — daily session summary endpoint.

SIMPLE MODE: Reads from a flat JSON file (data/jornada-session.json) instead of the DB.
When a PDF is downloaded, a minimal entry is appended. When the resumen is requested,
the file is read, grouped, formatted into a text report, and then CLEARED.
"""

from fastapi import APIRouter, Response

from app.domains.jornada.service import (
    get_jornada_results,
    format_report,
    clear_jornada_log,
)

router = APIRouter(prefix="/jornada", tags=["Jornada"])


@router.get("/resumen")
async def jornada_resumen():
    """Return a summary of today's downloaded PDFs.

    Reads from the flat jornada log file (data/jornada-session.json),
    groups entries by test category, formats a plain text report,
    and CLEARS the log file after generating the report.

    No DB queries, no session markers — simple and reliable.
    """
    grouped = get_jornada_results()
    report = format_report(grouped)

    # Clear the log after generating the report
    clear_jornada_log()

    return Response(
        content=report,
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="resumen-jornada.txt"'
        },
    )


@router.get("/adelanto")
async def jornada_adelanto():
    """Return an adelanto (preview) of today's jornada WITHOUT clearing the log.

    Same format as /jornada/resumen but read-only — the log is preserved.
    Useful for headless auto mode 'r' ADELANTO option.
    """
    grouped = get_jornada_results()
    report = format_report(grouped)

    # Do NOT clear the log — this is a read-only preview

    return Response(
        content=report,
        media_type="text/plain; charset=utf-8",
        headers={
            "X-Jornada-Mode": "HASTA-AHORA",
        },
    )
