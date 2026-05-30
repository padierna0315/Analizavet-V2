"""Tests for DataQuarantinedException and BaulResult changes (T2)."""
import pytest
from app.domains.reception.schemas import DataQuarantinedException, BaulResult, NormalizedPatient, PatientSource


class TestDataQuarantinedException:
    """DataQuarantinedException carries quarantine metadata."""

    def test_exception_carries_session_code(self):
        """Exception must store the session_code for logging/retry."""
        exc = DataQuarantinedException(
            session_code="M5",
            source="LIS_OZELLE",
            quarantine_id=42,
        )
        assert exc.session_code == "M5"

    def test_exception_carries_source(self):
        """Exception must store the source for traceability."""
        exc = DataQuarantinedException(
            session_code="F2",
            source="LIS_FUJIFILM",
            quarantine_id=7,
        )
        assert exc.source == "LIS_FUJIFILM"

    def test_exception_carries_quarantine_id(self):
        """Exception must store the quarantine_id for reprocessing."""
        exc = DataQuarantinedException(
            session_code="A1",
            source="LIS_FILE",
            quarantine_id=99,
        )
        assert exc.quarantine_id == 99

    def test_exception_is_instance_of_exception(self):
        """DataQuarantinedException must be a subclass of Exception."""
        exc = DataQuarantinedException(
            session_code="M5",
            source="LIS_OZELLE",
            quarantine_id=1,
        )
        assert isinstance(exc, Exception)

    def test_exception_session_code_can_be_none(self):
        """session_code can be None for edge cases."""
        exc = DataQuarantinedException(
            session_code=None,
            source="LIS_OZELLE",
            quarantine_id=1,
        )
        assert exc.session_code is None


class TestBaulResultOptionalPatientId:
    """BaulResult.patient_id must be Optional for backward-compat."""

    def test_patient_id_accepts_none(self):
        """BaulResult can be constructed with patient_id=None."""
        normal = NormalizedPatient(
            name="Test",
            species="Canino",
            sex="Macho",
            has_age=True,
            age_value=2,
            age_unit="años",
            age_display="2 años",
            owner_name="Owner",
            source=PatientSource.LIS_OZELLE,
        )
        result = BaulResult(patient_id=None, created=False, patient=normal)
        assert result.patient_id is None

    def test_patient_id_still_accepts_int(self):
        """BaulResult still works with patient_id=int (backward-compat)."""
        normal = NormalizedPatient(
            name="Test",
            species="Canino",
            sex="Macho",
            has_age=True,
            age_value=2,
            age_unit="años",
            age_display="2 años",
            owner_name="Owner",
            source=PatientSource.LIS_OZELLE,
        )
        result = BaulResult(patient_id=42, created=True, patient=normal)
        assert result.patient_id == 42
