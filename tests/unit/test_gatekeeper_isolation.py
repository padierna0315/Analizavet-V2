"""Tests for gatekeeper isolation: temporal check, fallback removal, code extraction.

PR 2 of 3 — patient-data-isolation-gatekeeper.
"""

import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, delete

from app.domains.reception.service import ReceptionService
from app.domains.patients.models import Patient
from app.domains.reception.schemas import RawPatientInput, PatientSource
from app.services.session_code_extractor import SessionCodeExtractor
from app.shared.models.data_quarantine import DataQuarantine, QuarantineStatus


# ═══════════════════════════════════════════════════════════════════════════════
# SessionCodeExtractor — RED phase (code already exists, testing NEW usages)
# ═══════════════════════════════════════════════════════════════════════════════


class TestSessionCodeExtractorGatekeeper:
    """Tests for SessionCodeExtractor usage at gatekeeper boundaries."""

    def test_extract_valid_code_with_name(self):
        """'M5 KIARA' → 'M5'"""
        assert SessionCodeExtractor.extract("M5 KIARA") == "M5"

    def test_extract_valid_code_no_space(self):
        """'M5KIARA' → 'M5'"""
        assert SessionCodeExtractor.extract("M5KIARA") == "M5"

    def test_extract_valid_code_with_hyphen(self):
        """'M5-KIARA' → 'M5'"""
        assert SessionCodeExtractor.extract("M5-KIARA") == "M5"

    def test_extract_name_without_code_returns_none(self):
        """'KIARA' → None — no code prefix"""
        assert SessionCodeExtractor.extract("KIARA") is None

    def test_extract_empty_string_returns_none(self):
        """'' → None — empty input"""
        assert SessionCodeExtractor.extract("") is None

    def test_extract_whitespace_only_returns_none(self):
        """'   ' → None"""
        assert SessionCodeExtractor.extract("   ") is None

    def test_extract_digit_first_returns_none(self):
        """'5M KIARA' → None — code must start with letter"""
        assert SessionCodeExtractor.extract("5M KIARA") is None

    def test_extract_multi_letter_code(self):
        """'AA5 TEST' → None — only single letter prefix valid"""
        assert SessionCodeExtractor.extract("AA5 TEST") is None


# ═══════════════════════════════════════════════════════════════════════════════
# Temporal Isolation Check — RED phase (new behavior)
# ═══════════════════════════════════════════════════════════════════════════════


class TestTemporalIsolationCheck:
    """Tests for temporal isolation in ReceptionService.receive()."""

    @pytest.mark.asyncio
    async def test_temporal_violation_creates_new_patient(self, session: AsyncSession):
        """When received_at is 10s BEFORE created_at, data must NOT attach to existing patient."""
        await session.execute(delete(Patient))
        await session.commit()

        # Pre-create patient created 20 seconds ago
        now = datetime.now(timezone.utc)
        created_time = now - timedelta(seconds=20)
        existing = Patient(
            name="Temporal Test",
            species="Canino",
            sex="Macho",
            owner_name="Owner",
            source=PatientSource.APPSHEET.value,
            session_code="T1",
            sources_received=[PatientSource.APPSHEET.value],
            normalized_name="temporal test",
            normalized_owner="owner",
            created_at=created_time,
            appsheet_confirmed=True,
        )
        session.add(existing)
        await session.commit()
        await session.refresh(existing)

        service = ReceptionService()

        # Use MANUAL source — temporal isolation check applies to non-machine
        # sources. Machine sources are now gated by AppSheet authority first.
        received_time = now - timedelta(seconds=30)
        raw_input = RawPatientInput(
            raw_string="Test Canino 3a Real Owner",
            session_code="T1",
            source=PatientSource.MANUAL,
            received_at=received_time,
        )

        result = await service.receive(raw_input, session)

        # Must NOT attach to existing patient (temporal violation)
        assert result.patient_id != existing.id, (
            f"Temporal violation: data should NOT attach to existing patient {existing.id}"
        )
        # Should create a new patient instead
        assert result.created is True

    @pytest.mark.asyncio
    async def test_temporal_ok_when_received_after_created(self, session: AsyncSession):
        """When received_at is AFTER created_at, data attaches to existing patient."""
        await session.execute(delete(Patient))
        await session.commit()

        now = datetime.now(timezone.utc)
        created_time = now - timedelta(seconds=60)
        existing = Patient(
            name="Valid Temporal",
            species="Felino",
            sex="Hembra",
            owner_name="Owner",
            source=PatientSource.APPSHEET.value,
            session_code="V1",
            sources_received=[PatientSource.APPSHEET.value],
            normalized_name="valid temporal",
            normalized_owner="owner",
            created_at=created_time,
            appsheet_confirmed=True,
        )
        session.add(existing)
        await session.commit()
        await session.refresh(existing)

        service = ReceptionService()

        # Data received 30 seconds ago (well AFTER patient was created)
        received_time = now - timedelta(seconds=30)
        raw_input = RawPatientInput(
            raw_string="Valid Temporal Machine",
            session_code="V1",
            source=PatientSource.LIS_OZELLE,
            received_at=received_time,
        )

        result = await service.receive(raw_input, session)

        # Must attach to existing patient (no temporal violation)
        assert result.patient_id == existing.id
        assert result.created is False

    @pytest.mark.asyncio
    async def test_temporal_tolerance_within_3s(self, session: AsyncSession):
        """When received_at is 3s before created_at (within 5s tolerance), no violation."""
        await session.execute(delete(Patient))
        await session.commit()

        now = datetime.now(timezone.utc)
        created_time = now - timedelta(seconds=50)
        existing = Patient(
            name="Tolerance Test",
            species="Canino",
            sex="Macho",
            owner_name="Owner",
            source=PatientSource.APPSHEET.value,
            session_code="TOL1",
            sources_received=[PatientSource.APPSHEET.value],
            normalized_name="tolerance test",
            normalized_owner="owner",
            created_at=created_time,
            appsheet_confirmed=True,
        )
        session.add(existing)
        await session.commit()
        await session.refresh(existing)

        service = ReceptionService()

        # Data received 53 seconds ago (3s BEFORE patient was created — within 5s tolerance)
        received_time = now - timedelta(seconds=53)
        raw_input = RawPatientInput(
            raw_string="Tolerance Test Machine",
            session_code="TOL1",
            source=PatientSource.LIS_OZELLE,
            received_at=received_time,
        )

        result = await service.receive(raw_input, session)

        # Within tolerance → should attach to existing
        assert result.patient_id == existing.id
        assert result.created is False

    @pytest.mark.asyncio
    async def test_temporal_exact_same_time(self, session: AsyncSession):
        """When received_at equals created_at exactly, no violation."""
        await session.execute(delete(Patient))
        await session.commit()

        fixed_time = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        existing = Patient(
            name="Same Time",
            species="Canino",
            sex="Macho",
            owner_name="Owner",
            source=PatientSource.APPSHEET.value,
            session_code="S1",
            sources_received=[PatientSource.APPSHEET.value],
            normalized_name="same time",
            normalized_owner="owner",
            created_at=fixed_time,
            appsheet_confirmed=True,
        )
        session.add(existing)
        await session.commit()
        await session.refresh(existing)

        service = ReceptionService()

        raw_input = RawPatientInput(
            raw_string="Same Time Machine",
            session_code="S1",
            source=PatientSource.LIS_FUJIFILM,
            received_at=fixed_time,
        )

        result = await service.receive(raw_input, session)

        # Same time → should attach to existing
        assert result.patient_id == existing.id
        assert result.created is False

    @pytest.mark.asyncio
    async def test_temporal_check_skipped_when_no_session_code(self, session: AsyncSession):
        """When no session_code is provided, temporal check is irrelevant — skip it.
        Uses MANUAL source (machine sources are now gated first)."""
        await session.execute(delete(Patient))
        await session.commit()

        service = ReceptionService()

        raw_input = RawPatientInput(
            raw_string="NoCode Canino 5a Owner",
            session_code=None,
            source=PatientSource.MANUAL,
            received_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )

        result = await service.receive(raw_input, session)

        # Should create new patient (no session_code to match)
        assert result.created is True


# ═══════════════════════════════════════════════════════════════════════════════
# Fallback Removal — Fujifilm name-only match (RED phase)
# ═══════════════════════════════════════════════════════════════════════════════


class TestFujifilmFallbackRemoved:
    """Verify Fujifilm name-only fallback is removed — name alone never matches."""

    @pytest.mark.asyncio
    async def test_fujifilm_no_session_code_creates_new_patient(self, session: AsyncSession):
        """Fujifilm data without session_code is now quarantined — machine
        sources cannot create patients without AppSheet confirmation."""
        from app.domains.reception.schemas import DataQuarantinedException

        await session.execute(delete(Patient))
        await session.commit()

        # Pre-create patient with same normalized_name that WOULD match under old logic
        existing = Patient(
            name="ORION",
            species="Canino",
            sex="Macho",
            owner_name="Owner",
            source=PatientSource.LIS_FUJIFILM.value,
            session_code="F2",  # Has code but new data won't have it
            sources_received=[PatientSource.LIS_FUJIFILM.value],
            normalized_name="orion",
            normalized_owner="owner",
        )
        session.add(existing)
        await session.commit()
        await session.refresh(existing)

        service = ReceptionService()

        # New Fujifilm data WITHOUT session_code — same name "ORION"
        raw_input = RawPatientInput(
            raw_string="ORION",
            session_code=None,
            source=PatientSource.LIS_FUJIFILM,
            received_at=datetime.now(timezone.utc),
        )

        # Machine source without confirmed patient → quarantine
        with pytest.raises(DataQuarantinedException):
            await service.receive(raw_input, session)

    @pytest.mark.asyncio
    async def test_fujifilm_with_code_matches_by_code(self, session: AsyncSession):
        """Fujifilm data WITH valid session_code still matches existing patient by code."""
        await session.execute(delete(Patient))
        await session.commit()

        existing = Patient(
            name="ORION",
            species="Canino",
            sex="Macho",
            owner_name="Owner",
            source=PatientSource.LIS_FUJIFILM.value,
            session_code="F2",
            sources_received=[PatientSource.LIS_FUJIFILM.value],
            normalized_name="orion",
            normalized_owner="owner",
            appsheet_confirmed=True,  # ← AppSheet authority gate requires confirmation
        )
        session.add(existing)
        await session.commit()
        await session.refresh(existing)

        service = ReceptionService()

        # Fujifilm data WITH session_code "F2"
        raw_input = RawPatientInput(
            raw_string="ORION",
            session_code="F2",
            source=PatientSource.LIS_FUJIFILM,
            received_at=datetime.now(timezone.utc),
        )

        result = await service.receive(raw_input, session)

        # Must match by session_code
        assert result.patient_id == existing.id
        assert result.created is False


# ═══════════════════════════════════════════════════════════════════════════════
# Fallback Removal — Ozelle name-only match (RED phase)
# ═══════════════════════════════════════════════════════════════════════════════


class TestOzelleFallbackRemoved:
    """Verify Ozelle name-only fallback is removed — name alone never matches."""

    @pytest.mark.asyncio
    async def test_ozelle_no_session_code_creates_new_patient(self, session: AsyncSession):
        """Ozelle data without session_code is now quarantined — machine
        sources cannot create patients without AppSheet confirmation."""
        from app.domains.reception.schemas import DataQuarantinedException

        await session.execute(delete(Patient))
        await session.commit()

        # Pre-create patient with same normalized_name BUT different owner+species
        existing = Patient(
            name="KIARA",
            species="Canino",
            sex="Hembra",
            owner_name="Different Owner",
            source=PatientSource.APPSHEET.value,
            session_code="M5",
            sources_received=[PatientSource.APPSHEET.value],
            normalized_name="kiara",
            normalized_owner="different owner",
        )
        session.add(existing)
        await session.commit()
        await session.refresh(existing)

        service = ReceptionService()

        raw_input = RawPatientInput(
            raw_string="KIARA Felino 2a Real Owner",
            session_code=None,
            source=PatientSource.LIS_OZELLE,
            received_at=datetime.now(timezone.utc),
        )

        # Machine source without confirmed patient → quarantine
        with pytest.raises(DataQuarantinedException):
            await service.receive(raw_input, session)

    @pytest.mark.asyncio
    async def test_ozelle_with_code_matches_by_code(self, session: AsyncSession):
        """Ozelle data WITH valid session_code still matches existing patient by code."""
        await session.execute(delete(Patient))
        await session.commit()

        existing = Patient(
            name="KIARA",
            species="Felino",
            sex="Hembra",
            owner_name="Owner",
            source=PatientSource.APPSHEET.value,
            session_code="M5",
            sources_received=[PatientSource.APPSHEET.value],
            normalized_name="kiara",
            normalized_owner="owner",
            appsheet_confirmed=True,  # ← AppSheet authority gate requires confirmation
        )
        session.add(existing)
        await session.commit()
        await session.refresh(existing)

        service = ReceptionService()

        # Ozelle data WITH session_code "M5"
        raw_input = RawPatientInput(
            raw_string="M5 KIARA Felino 2a Owner",
            session_code="M5",
            source=PatientSource.LIS_OZELLE,
            received_at=datetime.now(timezone.utc),
        )

        result = await service.receive(raw_input, session)

        # Must match by session_code
        assert result.patient_id == existing.id
        assert result.created is False


# ═══════════════════════════════════════════════════════════════════════════════
# Quarantine Model Sanity
# ═══════════════════════════════════════════════════════════════════════════════


class TestQuarantineModelUsage:
    """Verify DataQuarantine model works for gatekeeper rejection scenarios."""

    def test_quarantine_status_enum_values(self):
        """QuarantineStatus has expected lifecycle values."""
        assert QuarantineStatus.PENDING.value == "pending"
        assert QuarantineStatus.REVIEWED.value == "reviewed"
        assert QuarantineStatus.DISCARDED.value == "discarded"
        assert QuarantineStatus.FORCED.value == "forced"

    def test_quarantine_default_status_is_pending(self):
        """DataQuarantine defaults to PENDING status."""
        q = DataQuarantine(
            source="ozelle",
            raw_data="RAW|HL7|DATA",
            received_at=datetime.now(timezone.utc),
            rejection_reason="missing_code",
        )
        assert q.status == QuarantineStatus.PENDING.value

    def test_quarantine_missing_code_reason(self):
        """Quarantine can track missing_code rejection."""
        q = DataQuarantine(
            source="fujifilm",
            raw_data="ORION",
            received_at=datetime.now(timezone.utc),
            rejection_reason="missing_code",
        )
        assert q.rejection_reason == "missing_code"
        assert q.source == "fujifilm"

    def test_quarantine_temporal_mismatch_reason(self):
        """Quarantine can track temporal_mismatch rejection."""
        q = DataQuarantine(
            source="appsheet",
            raw_data='{"name": "test"}',
            received_at=datetime.now(timezone.utc),
            rejection_reason="temporal_mismatch",
        )
        assert q.rejection_reason == "temporal_mismatch"
