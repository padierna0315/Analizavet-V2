"""Tests for quarantine auto-reprocess trigger in _link_quarantined_items().

Verifies that after a quarantined item is linked (status='forced'),
reprocess_quarantined.send() is called as a fire-and-forget trigger.
"""

import pytest
from unittest.mock import patch, MagicMock
from sqlmodel import select, delete
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.reception.appsheet_service import AppSheetSyncService
from app.domains.reception.schemas import PatientSource
from app.domains.patients.models import Patient
from app.domains.exam_order.models import ExamOrder
from app.shared.models.data_quarantine import DataQuarantine
from app.services.appsheet import AppSheetPatient


@pytest.mark.asyncio
async def test_link_quarantined_triggers_reprocess(session: AsyncSession):
    """GIVEN a quarantined item linked by AppSheet sync
    WHEN the link happens
    THEN reprocess_quarantined.send() is called with the quarantine ID."""
    await session.execute(delete(ExamOrder))
    await session.execute(delete(DataQuarantine))
    await session.execute(delete(Patient))
    await session.commit()

    # Insert pending quarantine
    q = DataQuarantine(
        source=PatientSource.LIS_OZELLE.value,
        raw_data="A1 KIARA",
        received_at=datetime.now(timezone.utc),
        rejection_reason="awaiting_appsheet",
        session_code="A1",
        status="pending",
    )
    session.add(q)
    await session.commit()
    q_id = q.id

    sync_svc = AppSheetSyncService()
    appsheet_patients = [
        AppSheetPatient(
            Codigo_Corto="A1",
            Doctora="Aura",
            Categoria_Examen="Examen de sangre",
            Examen_Especifico="Perfil Básico (PQ1)",
            Nombre_Mascota="Kiara",
            Especie="Felino",
            Sexo="Hembra",
            Edad_Numero="7",
            Edad_Unidad="Años",
            Nombre_Tutor="María",
            Raza="Mestizo",
        )
    ]

    with patch(
        "app.tasks.quarantine_reprocess.reprocess_quarantined.send"
    ) as mock_send:
        await sync_svc.sync_from_appsheet(appsheet_patients, session)

        # Verify send was called for the linked quarantine item
        mock_send.assert_called_once_with(q_id)


@pytest.mark.asyncio
async def test_no_quarantine_no_reprocess_trigger(session: AsyncSession):
    """GIVEN no quarantined items exist
    WHEN AppSheet sync runs
    THEN reprocess_quarantined.send() is NOT called."""
    await session.execute(delete(ExamOrder))
    await session.execute(delete(DataQuarantine))
    await session.execute(delete(Patient))
    await session.commit()

    sync_svc = AppSheetSyncService()
    appsheet_patients = [
        AppSheetPatient(
            Codigo_Corto="A2",
            Doctora="Aura",
            Categoria_Examen="Examen de sangre",
            Examen_Especifico="Perfil Básico (PQ1)",
            Nombre_Mascota="Rocky",
            Especie="Canino",
            Sexo="Macho",
            Edad_Numero="5",
            Edad_Unidad="Años",
            Nombre_Tutor="Juan",
            Raza="Mestizo",
        )
    ]

    with patch(
        "app.tasks.quarantine_reprocess.reprocess_quarantined.send"
    ) as mock_send:
        await sync_svc.sync_from_appsheet(appsheet_patients, session)

        # No quarantine items exist, so send should NOT be called
        mock_send.assert_not_called()
