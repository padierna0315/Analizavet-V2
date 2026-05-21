"""Integration tests for quarantine review router endpoints.

PR 3 of 3 — patient-data-isolation-gatekeeper.
"""

import pytest
from httpx import AsyncClient
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.shared.models.data_quarantine import DataQuarantine, QuarantineStatus


def _make_q(**kwargs):
    """Factory for DataQuarantine test records."""
    defaults = dict(
        source="ozelle",
        raw_data="HL7: KIARA",
        received_at=datetime.now(timezone.utc),
        rejection_reason="missing_code",
        status="pending",
    )
    defaults.update(kwargs)
    return DataQuarantine(**defaults)


# ══════════════════════════════════════════════════════════════════════════
# GET /quarantine — list pending items
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_quarantine_list_returns_200(client: AsyncClient, session: AsyncSession):
    """Endpoint exists and returns success response."""
    response = await client.get("/quarantine")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_quarantine_list_empty_shows_message(client: AsyncClient, session: AsyncSession):
    """Empty quarantine list shows user-friendly message."""
    response = await client.get("/quarantine")
    assert response.status_code == 200
    assert "Sin elementos" in response.text or "No hay" in response.text


@pytest.mark.asyncio
async def test_quarantine_list_shows_pending_item(client: AsyncClient, session: AsyncSession):
    """Pending quarantine item appears in the returned HTML table."""
    q = _make_q(source="ozelle", raw_data="HL7: M5 KIARA", rejection_reason="missing_code")
    session.add(q)
    await session.commit()

    response = await client.get("/quarantine")
    assert response.status_code == 200
    assert "KIARA" in response.text
    assert "ozelle" in response.text
    assert "missing_code" in response.text


@pytest.mark.asyncio
async def test_quarantine_list_only_pending(client: AsyncClient, session: AsyncSession):
    """Only pending items are listed — not discarded or forced ones."""
    q_pending = _make_q(raw_data="PENDING", status="pending")
    q_discarded = _make_q(raw_data="DISCARDED", status="discarded")
    q_forced = _make_q(raw_data="FORCED", status="forced")
    session.add_all([q_pending, q_discarded, q_forced])
    await session.commit()

    response = await client.get("/quarantine")
    assert "PENDING" in response.text
    assert "DISCARDED" not in response.text
    assert "FORCED" not in response.text


# ══════════════════════════════════════════════════════════════════════════
# POST /quarantine/{id}/force-match — admin assigns session code
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_force_match_sets_status_to_forced(client: AsyncClient, session: AsyncSession):
    """Valid session code → status='forced' and session_code set on record."""
    q = _make_q(source="ozelle", raw_data="KIARA", rejection_reason="missing_code")
    session.add(q)
    await session.commit()
    await session.refresh(q)

    response = await client.post(
        f"/quarantine/{q.id}/force-match",
        data={"session_code": "M5"},
    )

    assert response.status_code == 200
    await session.refresh(q)
    assert q.status == "forced"
    assert q.session_code == "M5"


@pytest.mark.asyncio
async def test_force_match_not_found_returns_404(client: AsyncClient, session: AsyncSession):
    """Non-existent quarantine ID returns 404."""
    response = await client.post(
        "/quarantine/99999/force-match",
        data={"session_code": "M5"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_force_match_invalid_code_returns_400(client: AsyncClient, session: AsyncSession):
    """Session code without valid prefix (^[A-Z]\d+) returns 400 error."""
    q = _make_q(source="ozelle", raw_data="KIARA", rejection_reason="missing_code")
    session.add(q)
    await session.commit()
    await session.refresh(q)

    response = await client.post(
        f"/quarantine/{q.id}/force-match",
        data={"session_code": "KIARA"},  # no valid code prefix
    )

    assert response.status_code == 400
    await session.refresh(q)
    assert q.status == "pending"  # unchanged


@pytest.mark.asyncio
async def test_force_match_already_processed_returns_409(client: AsyncClient, session: AsyncSession):
    """Force-matching an already-processed item returns 409 Conflict."""
    q = _make_q(status="discarded", session_code="M5")
    session.add(q)
    await session.commit()
    await session.refresh(q)

    response = await client.post(
        f"/quarantine/{q.id}/force-match",
        data={"session_code": "M6"},
    )
    assert response.status_code == 409


# ══════════════════════════════════════════════════════════════════════════
# POST /quarantine/{id}/discard — soft-delete item
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_discard_sets_status_to_discarded(client: AsyncClient, session: AsyncSession):
    """Discard sets status to 'discarded' — soft-delete, not physical delete."""
    q = _make_q(source="fujifilm", raw_data="PATIENT:CANELA", rejection_reason="invalid_code")
    session.add(q)
    await session.commit()
    await session.refresh(q)

    response = await client.post(f"/quarantine/{q.id}/discard")

    assert response.status_code == 200
    await session.refresh(q)
    assert q.status == "discarded"
    # Verify record still exists (not physically deleted)
    stmt = select(DataQuarantine).where(DataQuarantine.id == q.id)
    result = await session.execute(stmt)
    assert result.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_discard_not_found_returns_404(client: AsyncClient, session: AsyncSession):
    """Non-existent ID returns 404."""
    response = await client.post("/quarantine/99999/discard")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_discard_already_discarded_is_idempotent(client: AsyncClient, session: AsyncSession):
    """Discarding an already-discarded item succeeds (idempotent)."""
    q = _make_q(raw_data="OLD", status="discarded")
    session.add(q)
    await session.commit()
    await session.refresh(q)

    response = await client.post(f"/quarantine/{q.id}/discard")
    assert response.status_code == 200
    await session.refresh(q)
    assert q.status == "discarded"


# ══════════════════════════════════════════════════════════════════════════
# GET /quarantine/count — badge counter
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_count_zero_when_empty(client: AsyncClient, session: AsyncSession):
    """Returns 0 when no pending items exist."""
    response = await client.get("/quarantine/count")
    assert response.status_code == 200
    assert "0" in response.text


@pytest.mark.asyncio
async def test_count_returns_pending_only(client: AsyncClient, session: AsyncSession):
    """Count only pending items, not discarded or forced."""
    q1 = _make_q(raw_data="R1", status="pending")
    q2 = _make_q(raw_data="R2", status="pending")
    q3 = _make_q(raw_data="R3", status="discarded")
    q4 = _make_q(raw_data="R4", status="forced")
    session.add_all([q1, q2, q3, q4])
    await session.commit()

    response = await client.get("/quarantine/count")
    assert response.status_code == 200
    assert "2" in response.text
