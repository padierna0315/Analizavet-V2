import pytest
from app.domains.reception.normalizer import parse_patient_string
from app.domains.reception.schemas import PatientSource


def test_standard_canina_with_compound_owner():
    result = parse_patient_string("kitty felina 2a Laura Cepeda", PatientSource.LIS_OZELLE)
    assert result.name == "Kitty"
    assert result.species == "Felino"
    assert result.sex == "Hembra"
    assert result.age_value == 2
    assert result.age_unit == "años"
    assert result.age_display == "2 años"
    assert result.owner_name == "Laura Cepeda"
    assert result.has_age is True


def test_standard_canino_months():
    result = parse_patient_string("Rocky canino 6m Juan Pérez", PatientSource.LIS_OZELLE)
    assert result.name == "Rocky"
    assert result.species == "Canino"
    assert result.sex == "Macho"
    assert result.age_value == 6
    assert result.age_unit == "meses"
    assert result.age_display == "6 meses"
    assert result.owner_name == "Juan Pérez"
    assert result.has_age is True


def test_singular_age_1_año():
    result = parse_patient_string("luna felina 1a Maria", PatientSource.LIS_OZELLE)
    assert result.age_value == 1
    assert result.age_unit == "años"
    assert result.age_display == "1 año"


def test_singular_age_1_mes():
    result = parse_patient_string("luna felina 1m Maria", PatientSource.LIS_OZELLE)
    assert result.age_value == 1
    assert result.age_unit == "meses"
    assert result.age_display == "1 mes"


def test_compound_owner_name():
    result = parse_patient_string("rocky canino 3a Juan de la Torre", PatientSource.LIS_OZELLE)
    assert result.owner_name == "Juan De La Torre"


def test_compound_owner_multi_word():
    result = parse_patient_string("luna felina 2a Ana María López García", PatientSource.LIS_OZELLE)
    assert result.owner_name == "Ana María López García"


def test_uppercase_input():
    result = parse_patient_string("KITTY FELINA 2A LAURA CEPEDA", PatientSource.LIS_OZELLE)
    assert result.name == "Kitty"
    assert result.species == "Felino"
    assert result.sex == "Hembra"
    assert result.age_display == "2 años"
    assert result.owner_name == "Laura Cepeda"


def test_mixed_case_input():
    result = parse_patient_string("kItTy FeLiNa 2a lAuRa CePeDa", PatientSource.LIS_OZELLE)
    assert result.name == "Kitty"
    assert result.species == "Felino"
    assert result.sex == "Hembra"
    assert result.owner_name == "Laura Cepeda"


def test_coproscopic_canina():
    result = parse_patient_string("kitty felina Laura Cepeda", PatientSource.LIS_OZELLE)
    assert result.has_age is False
    assert result.age_value is None
    assert result.age_display is None
    assert result.owner_name == "Laura Cepeda"


def test_coproscopic_compound_owner():
    result = parse_patient_string("rocky canino Ana María López", PatientSource.LIS_OZELLE)
    assert result.has_age is False
    assert result.owner_name == "Ana María López"

@pytest.mark.parametrize("token,expected_species,expected_sex", [
    ("canino", "Canino", "Macho"),
    ("canina", "Canino", "Hembra"),
    ("felino", "Felino", "Macho"),
    ("felina", "Felino", "Hembra"),
])
def test_all_species_sex_combos(token, expected_species, expected_sex):
    result = parse_patient_string(f"pet {token} 1a Owner", PatientSource.LIS_OZELLE)
    assert result.species == expected_species
    assert result.sex == expected_sex


def test_invalid_species_raises():
    with pytest.raises(ValueError) as excinfo:
        parse_patient_string("rocky perro 2a Juan", PatientSource.LIS_OZELLE)
    assert "Especie no reconocida: perro" in str(excinfo.value)


def test_empty_string_raises():
    with pytest.raises(ValueError) as excinfo:
        parse_patient_string("", PatientSource.LIS_OZELLE)
    assert "El string del paciente no puede estar vacío" in str(excinfo.value)


def test_too_short_raises():
    with pytest.raises(ValueError) as excinfo:
        parse_patient_string("kitty", PatientSource.LIS_OZELLE)
    assert "Formato inválido. Mínimo: nombre especie" in str(excinfo.value)


def test_missing_tutor_assigned_default():
    result = parse_patient_string("kira canina 1a", PatientSource.LIS_OZELLE)
    assert result.name == "Kira"
    assert result.species == "Canino"
    assert result.sex == "Hembra"
    assert result.age_value == 1
    assert result.owner_name == "Sin Tutor"

def test_missing_tutor_no_age():
    result = parse_patient_string("kitty felina", PatientSource.LIS_OZELLE)
    assert result.name == "Kitty"
    assert result.has_age is False
    assert result.owner_name == "Sin Tutor"


def test_source_carried_through():
    result = parse_patient_string("kitty felina 2a Laura", PatientSource.LIS_FILE)
    assert result.source == PatientSource.LIS_FILE