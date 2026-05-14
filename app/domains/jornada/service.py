"""Jornada service — session tracking and daily report generation."""

import os
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.shared.models.test_result import TestResult

SESSION_MARKER = "/tmp/analizavet-session-start"

# Category definitions: (key, icon_and_name, test_type_code_filter)
_CATEGORIES = [
    ("perfiles", "🔬 Perfiles básicos", "CHEM"),
    ("coprologicos", "🦠 Coprológicos", "COPROSC"),
    ("coprologicos_seriados", "🦠🔬 Coprológicos seriados", "COPROSC_SERIADO"),
    ("citoquimicos", "💛 Citoquímicos", "CITO"),
]


def read_session_start() -> float | None:
    """Read the Unix timestamp from the session marker file.

    Returns the timestamp as a float (seconds since epoch),
    or None if the marker file does not exist or cannot be read.
    """
    try:
        with open(SESSION_MARKER) as f:
            raw = f.read().strip()
            if not raw:
                return None
            return float(raw)
    except (FileNotFoundError, ValueError, OSError):
        return None


def _group_results(results: list[TestResult]) -> dict[str, list[dict]]:
    """Group TestResult rows into the four jornada categories.

    Returns a dict mapping category_key -> list of result dicts.
    """
    grouped: dict[str, list[dict]] = {
        "perfiles": [],
        "coprologicos": [],
        "coprologicos_seriados": [],
        "citoquimicos": [],
    }

    for tr in results:
        patient = tr.patient
        result_dict = {
            "id": tr.id,
            "name": patient.name if patient else "?",
            "species": patient.species if patient else "?",
            "owner": patient.owner_name if patient else "?",
            "doctor": tr.doctor_name or "Sin médico",
            "test_type": tr.test_type,
        }

        code = (tr.test_type_code or "").strip().upper()

        if code == "CHEM":
            grouped["perfiles"].append(result_dict)
        elif code == "COPROSC":
            test_type = (tr.test_type or "").lower()
            if "seriado" in test_type:
                grouped["coprologicos_seriados"].append(result_dict)
            else:
                grouped["coprologicos"].append(result_dict)
        elif code == "CITO":
            grouped["citoquimicos"].append(result_dict)

    return grouped


def _format_category(category_name: str, items: list[dict]) -> str:
    """Format a single category section of the report."""
    lines = [f"\n{category_name}:"]
    if not items:
        lines.append("  (Sin resultados)")
    else:
        for item in items:
            lines.append(
                f"  • {item['name']} — {item['species']} — tutor: {item['owner']} — médico: {item['doctor']}"
            )
    return "\n".join(lines)


def format_report(grouped: dict[str, list[dict]]) -> str:
    """Build the full text/plain jornada report from grouped results.

    Args:
        grouped: dict from _group_results() with category_key -> list of dicts.

    Returns:
        Plain text report as a single string.
    """
    total = sum(len(items) for items in grouped.values())
    if total == 0:
        return (
            "🐾 Reporte de jornada — Huellas Lab\n"
            "No hay reportes generados en esta sesión."
        )

    # Collect unique dates
    dates_set: set[str] = set()

    dates_line = ""
    if dates_set:
        dates_line = f"📅 Reportes de los días {', '.join(sorted(dates_set))}"

    parts = ["🐾 Reporte de jornada — Huellas Lab"]
    if dates_line:
        parts.append(dates_line)

    # Only show non-empty categories + the first empty one (to indicate section exists)
    category_configs = [
        ("perfiles", "🔬 Perfiles básicos del día"),
        ("coprologicos", "🦠 Coprológicos"),
        ("coprologicos_seriados", "🦠🔬 Coprológicos seriados"),
        ("citoquimicos", "💛 Citoquímicos"),
    ]

    for key, display_name in category_configs:
        items = grouped.get(key, [])
        # For the header, add "({count})" only for perfiles
        if key == "perfiles":
            header = f"{display_name} ({len(items)})"
        else:
            header = display_name
        parts.append(_format_category(header, items))

    parts.append(f"\n✅ Total: {total} reportes generados")
    return "\n".join(parts)


async def get_session_results(
    session_start: float, db_session: AsyncSession
) -> dict[str, list[dict]]:
    """Query TestResult rows created after session_start and group by category.

    Args:
        session_start: Unix timestamp (seconds since epoch).
        db_session: Async SQLAlchemy session.

    Returns:
        Dict mapping category_key -> list of result dicts.
    """
    start_dt = datetime.fromtimestamp(session_start, tz=timezone.utc)

    stmt = (
        select(TestResult)
        .options(selectinload(TestResult.patient))
        .where(TestResult.created_at >= start_dt)
        .order_by(TestResult.created_at.asc())
    )
    result = await db_session.execute(stmt)
    rows = result.scalars().all()

    return _group_results(list(rows))
