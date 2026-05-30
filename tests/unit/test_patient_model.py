"""Tests for Patient model — appsheet_confirmed flag (T1)."""
import pytest
from app.domains.patients.models import Patient
from app.domains.reception.schemas import PatientSource


def test_appsheet_confirmed_defaults_to_false():
    """A new Patient must have appsheet_confirmed=False by default."""
    patient = Patient(
        name="Lucas",
        species="Canino",
        sex="Macho",
        owner_name="Owner",
        source=PatientSource.LIS_OZELLE.value,
        normalized_name="lucas",
        normalized_owner="owner",
    )
    assert patient.appsheet_confirmed is False


def test_appsheet_confirmed_can_be_set_true():
    """appsheet_confirmed can be explicitly set to True at construction."""
    patient = Patient(
        name="Lucas",
        species="Canino",
        sex="Macho",
        owner_name="Owner",
        source=PatientSource.APPSHEET.value,
        normalized_name="lucas",
        normalized_owner="owner",
        appsheet_confirmed=True,
    )
    assert patient.appsheet_confirmed is True


def test_appsheet_confirmed_persists_after_assign():
    """appsheet_confirmed can be set after construction and holds its value."""
    patient = Patient(
        name="Lucas",
        species="Canino",
        sex="Macho",
        owner_name="Owner",
        source=PatientSource.LIS_OZELLE.value,
        normalized_name="lucas",
        normalized_owner="owner",
    )
    assert patient.appsheet_confirmed is False
    patient.appsheet_confirmed = True
    assert patient.appsheet_confirmed is True
