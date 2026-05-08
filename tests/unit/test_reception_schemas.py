import pytest
from app.domains.reception.schemas import RawPatientInput, NormalizedPatient, PatientSource
from datetime import datetime


def test_raw_patient_strips_whitespace():
    # "  kitty felina 2a Laura  " → raw_string == "kitty felina 2a Laura"
    raw = RawPatientInput(
        raw_string="  kitty felina 2a Laura  ",
        source=PatientSource.LIS_OZELLE,
        received_at=datetime.utcnow()
    )
    assert raw.raw_string == "kitty felina 2a Laura"


def test_raw_patient_empty_string_raises():
    # empty string → ValidationError
    with pytest.raises(ValueError, match="raw_string cannot be empty"):
        RawPatientInput(
            raw_string="   ",
            source=PatientSource.LIS_OZELLE,
            received_at=datetime.utcnow()
        )


def test_raw_patient_source_enum():
    # PatientSource.LIS_OZELLE accepted
    raw = RawPatientInput(
        raw_string="test",
        source=PatientSource.LIS_OZELLE,
        received_at=datetime.utcnow()
    )
    assert raw.source == PatientSource.LIS_OZELLE


def test_normalized_patient_with_age():
    # has_age=True, all age fields set → valid
    patient = NormalizedPatient(
        name="kItTy",
        species="Felino",
        sex="Hembra",
        has_age=True,
        age_value=2,
        age_unit="años",
        age_display="2 años",
        owner_name="laura cepeda",
        source=PatientSource.LIS_OZELLE
    )
    assert patient.name == "Kitty"
    assert patient.owner_name == "Laura Cepeda"
    assert patient.age_value == 2
    assert patient.age_unit == "años"
    assert patient.age_display == "2 años"


def test_normalized_patient_coproscopic():
    # has_age=False, all age fields None → valid
    patient = NormalizedPatient(
        name="Copros",
        species="Felino",
        sex="Hembra",
        has_age=False,
        age_value=None,
        age_unit=None,
        age_display=None,
        owner_name="owner",
        source=PatientSource.MANUAL
    )
    assert patient.has_age is False
    assert patient.age_value is None
    assert patient.age_unit is None
    assert patient.age_display is None


def test_normalized_patient_age_inconsistency_raises():
    # has_age=True but age_value=None → ValidationError
    with pytest.raises(ValueError, match="When has_age is True, age_value, age_unit, and age_display must be set"):
        NormalizedPatient(
            name="Inconsistent",
            species="Canino",
            sex="Macho",
            has_age=True,
            age_value=None,
            age_unit="años",
            age_display="2 años",
            owner_name="owner",
            source=PatientSource.MANUAL
        )


def test_normalized_patient_name_capitalized():
    # name="KITTY" input should be stored as "Kitty"
    patient = NormalizedPatient(
        name="KITTY",
        species="Canino",
        sex="Macho",
        has_age=True,
        age_value=3,
        age_unit="años",
        age_display="3 años",
        owner_name="owner",
        source=PatientSource.MANUAL
    )
    assert patient.name == "Kitty"


def test_normalized_owner_name_capitalized():
    # owner_name="laura cepeda" → "Laura Cepeda"
    patient = NormalizedPatient(
        name="Test",
        species="Felino",
        sex="Hembra",
        has_age=True,
        age_value=1,
        age_unit="años",
        age_display="1 año",
        owner_name="juan de la torre",
        source=PatientSource.MANUAL
    )
    assert patient.owner_name == "Juan De La Torre"