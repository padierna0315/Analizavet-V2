import pytest
import pytest_asyncio
import base64
from datetime import datetime, timezone
from pathlib import Path
from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.domains.patients.models import Patient
from app.shared.models.test_result import TestResult
from app.shared.models.patient_image import PatientImage
from app.domains.taller.schemas import ImageUploadRequest, ImageUploadItem
from clinical_standards import get_parameter_name
from app.domains.taller.images import (
    ImageHandlingService,
    _parse_obs_identifier,
    _build_filename,
    _build_patient_folder,
    _sanitize_folder_name,
)


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as s:
        yield s
    await engine.dispose()


def make_valid_jpeg_base64() -> str:
    """Minimal valid JPEG as Base64 (1x1 white pixel)."""
    JPEG_1X1 = bytes([
        0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01,
        0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0xFF, 0xDB, 0x00, 0x43,
        0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08, 0x07, 0x07, 0x07, 0x09,
        0x09, 0x08, 0x0A, 0x0C, 0x14, 0x0D, 0x0C, 0x0B, 0x0B, 0x0C, 0x19, 0x12,
        0x13, 0x0F, 0x14, 0x1D, 0x1A, 0x1F, 0x1E, 0x1D, 0x1A, 0x1C, 0x1C, 0x20,
        0x24, 0x2E, 0x27, 0x20, 0x22, 0x2C, 0x23, 0x1C, 0x1C, 0x28, 0x37, 0x29,
        0x2C, 0x30, 0x31, 0x34, 0x34, 0x34, 0x1F, 0x27, 0x39, 0x3D, 0x38, 0x32,
        0x3C, 0x2E, 0x33, 0x34, 0x32, 0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01,
        0x00, 0x01, 0x01, 0x01, 0x11, 0x00, 0xFF, 0xC4, 0x00, 0x1F, 0x00, 0x00,
        0x01, 0x05, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
        0x09, 0x0A, 0x0B, 0xFF, 0xC4, 0x00, 0xB5, 0x10, 0x00, 0x02, 0x01, 0x03,
        0x03, 0x02, 0x04, 0x03, 0x05, 0x05, 0x04, 0x04, 0x00, 0x00, 0x01, 0x7D,
        0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01, 0x00, 0x00, 0x3F, 0x00, 0xFB, 0xD2,
        0x8A, 0x28, 0x03, 0xFF, 0xD9,
    ])
    return base64.b64encode(JPEG_1X1).decode()


async def create_test_result_in_db(session) -> TestResult:
    patient = Patient(
        name="Kitty", species="Felino", sex="Hembra",
        owner_name="Laura Cepeda", has_age=True,
        age_value=2, age_unit="años", age_display="2 años",
        source="LIS_OZELLE",
        normalized_name="kitty", normalized_owner="laura cepeda",
    )
    session.add(patient)
    await session.commit()
    await session.refresh(patient)

    tr = TestResult(
        patient_id=patient.id,
        test_type="Hemograma", test_type_code="CBC",
        source="LIS_OZELLE", status="pendiente",
        received_at=datetime.now(timezone.utc),
    )
    session.add(tr)
    await session.commit()
    await session.refresh(tr)
    return tr


# ── Parser tests (confirmed against real Ozelle log) ─────────────────────────

def test_parse_obs_identifier_main():
    base, suffix = _parse_obs_identifier("WBC_Main")
    assert base == "WBC"
    assert suffix == "Main"

def test_parse_obs_identifier_part():
    base, suffix = _parse_obs_identifier("LYM_Part3")
    assert base == "LYM"
    assert suffix == "Part3"

def test_parse_obs_identifier_part10():
    base, suffix = _parse_obs_identifier("EOS_Part10")
    assert base == "EOS"
    assert suffix == "Part10"

def test_parse_obs_identifier_histo():
    base, suffix = _parse_obs_identifier("PLT_Histo")
    assert base == "PLT"
    assert suffix == "Histo"

def test_parse_obs_identifier_distribution():
    base, suffix = _parse_obs_identifier("WBC_Distribution")
    assert base == "WBC"
    assert suffix == "Distribution"

def test_parse_obs_identifier_combined_rbc_plt():
    """RBC_PLT_Distribution is a special combined histogram."""
    base, suffix = _parse_obs_identifier("RBC_PLT_Distribution")
    assert base == "RBC_PLT"
    assert suffix == "Distribution"

def test_parse_obs_identifier_p_lcc():
    """P-LCC_Main has a hyphen in the base code."""
    base, suffix = _parse_obs_identifier("P-LCC_Main")
    assert base == "P-LCC"
    assert suffix == "Main"

def test_parse_obs_identifier_feces():
    base, suffix = _parse_obs_identifier("FECES_Distribution")
    assert base == "FECES"
    assert suffix == "Distribution"


# ── Translation tests ─────────────────────────────────────────────────────────

def test_translate_hematology_codes():
    assert get_parameter_name("WBC", short=True) == "Leucocitos"
    assert get_parameter_name("RBC", short=True) == "Eritrocitos"
    assert get_parameter_name("PLT", short=True) == "Plaquetas"
    assert get_parameter_name("LYM", short=True) == "Linfocitos" # LYM is mapped to LYM# in clinical_standards.py
    assert get_parameter_name("EOS", short=True) == "Eosinofilos" # EOS is mapped to EOS# in clinical_standards.py
    assert get_parameter_name("MON", short=True) == "Monocitos" # MON is mapped to MON# in clinical_standards.py
    assert get_parameter_name("BAS", short=True) == "Basofilos" # BAS is mapped to BAS# in clinical_standards.py

def test_translate_advanced_morphology():
    assert get_parameter_name("NST", short=True) == "Neutrofilos_Banda"
    assert get_parameter_name("NSG", short=True) == "Neutrofilos_Segmentados"
    assert get_parameter_name("NSH", short=True) == "Neutrofilos_Hipersegmentados"
    assert get_parameter_name("RET", short=True) == "Reticulocitos"
    assert get_parameter_name("SPH", short=True) == "Esferocitos"
    assert get_parameter_name("ETG", short=True) == "Eritrocitos_Fantasma"
    assert get_parameter_name("APLT", short=True) == "Plaquetas_Agregadas"

def test_translate_coproscopic_codes():
    assert get_parameter_name("BACI", short=True) == "Bacilos"
    assert get_parameter_name("COS", short=True) == "Cocos"
    assert get_parameter_name("YEA", short=True) == "Levaduras"

def test_translate_unknown_code():
    result = get_parameter_name("UNKNOWN_XYZ", short=True)
    assert "unknown_xyz" in result # It returns lowercased code

@pytest.mark.parametrize("code, expected", [
    ("NST/WBC", "Bandas_Leucocitos_Pct"),
    ("NST/NEU", "Bandas_Neutrofilos_Pct"),
    ("NSH/WBC", "Hipersegmentados_Leucocitos_Pct"),
    ("NSH/NEU", "Hipersegmentados_Neutrofilos_Pct"),
    ("MPV", "Volumen_Plaquetario_Medio"),
    ("PDW", "Distribucion_Plaquetaria"),
    ("PCT", "Plaquetocrito"),
])
def test_translate_composite_and_new_codes(code, expected, caplog):
    # Clear log records to ensure we only capture warnings from this call
    caplog.clear()
    
    # When checking for composite codes, the `_translate_base_code`
    # function will split the code by '/' if present. The
    # `caplog` fixture captures log messages.
    result = get_parameter_name(code, short=True)
    assert result == expected
    assert "Código de imagen desconocido" not in caplog.text


# ── Build filename tests ──────────────────────────────────────────────────────

def test_build_filename_main():
    filename, name_es = _build_filename("WBC_Main")
    assert filename == "Leucocitos_Main.jpg"
    assert name_es == "Leucocitos"

def test_build_filename_part():
    filename, _ = _build_filename("LYM_Part3")
    assert filename == "Linfocitos_Part3.jpg"

def test_build_filename_histo():
    filename, _ = _build_filename("PLT_Histo")
    assert filename == "Plaquetas_Histo.jpg"

def test_build_filename_distribution():
    filename, _ = _build_filename("WBC_Distribution")
    assert filename == "Leucocitos_Distribution.jpg"

def test_build_filename_rbc_plt_combined():
    filename, name_es = _build_filename("RBC_PLT_Distribution")
    assert filename == "Distribucion_RBC_PLT_Distribution.jpg"
    assert name_es == "Distribucion_RBC_PLT"

def test_build_filename_coproscopic():
    filename, name_es = _build_filename("BACI_Main")
    assert filename == "Bacilos_Main.jpg"
    assert name_es == "Bacilos"


# ── Folder name tests ─────────────────────────────────────────────────────────

def test_sanitize_folder_removes_spaces():
    assert _sanitize_folder_name("Laura Cepeda") == "LauraCepeda"

def test_sanitize_folder_removes_accents():
    assert _sanitize_folder_name("María López") == "MariaLopez"
    # Input comes capitalized from Normalizer (Recepción), so "Niña" → "Nina"
    assert _sanitize_folder_name("Niña") == "Nina"
    assert _sanitize_folder_name("Señora Ríos") == "SenoraRios"
    # Better than Ozelle's approach (ni_a, Se_ora_R_os)

def test_build_patient_folder_structure():
    received = datetime(2026, 4, 24, tzinfo=timezone.utc)
    folder = _build_patient_folder("Kitty", "Laura Cepeda", received, "./images")
    assert "Kitty_LauraCepeda" in str(folder)
    assert "20260424" in str(folder)


# ── Integration: save_images ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_save_single_image_with_real_obs_id(session, tmp_path):
    """Use real Ozelle OBX identifier format: WBC_Main."""
    tr = await create_test_result_in_db(session)
    service = ImageHandlingService()
    service._base_dir = str(tmp_path)

    request = ImageUploadRequest(
        test_result_id=tr.id,
        patient_name="Kitty",
        owner_name="Laura Cepeda",
        received_at=datetime.now(timezone.utc),
        images=[
            ImageUploadItem(
                obs_identifier="WBC_Main",
                base64_data=make_valid_jpeg_base64(),
            )
        ],
    )
    result = await service.save_images(request, session)

    assert result.total_saved == 1
    assert result.total_failed == 0
    assert result.saved[0]["parameter_name_es"] == "Leucocitos"
    assert "Leucocitos_Main.jpg" in result.saved[0]["file_path"]
    assert Path(result.saved[0]["file_path"]).exists()


@pytest.mark.asyncio
async def test_save_multiple_images_real_format(session, tmp_path):
    """Multiple images with real Ozelle format."""
    tr = await create_test_result_in_db(session)
    service = ImageHandlingService()
    service._base_dir = str(tmp_path)

    request = ImageUploadRequest(
        test_result_id=tr.id,
        patient_name="Kitty",
        owner_name="Laura Cepeda",
        received_at=datetime.now(timezone.utc),
        images=[
            ImageUploadItem(obs_identifier="WBC_Main", base64_data=make_valid_jpeg_base64()),
            ImageUploadItem(obs_identifier="LYM_Part1", base64_data=make_valid_jpeg_base64()),
            ImageUploadItem(obs_identifier="PLT_Histo", base64_data=make_valid_jpeg_base64()),
            ImageUploadItem(obs_identifier="RBC_PLT_Distribution", base64_data=make_valid_jpeg_base64()),
        ],
    )
    result = await service.save_images(request, session)

    assert result.total_saved == 4
    assert result.total_failed == 0


@pytest.mark.asyncio
async def test_coproscopic_images(session, tmp_path):
    """Coproscopic images (BACI, COS, YEA) confirmed in real log."""
    tr = await create_test_result_in_db(session)
    service = ImageHandlingService()
    service._base_dir = str(tmp_path)

    request = ImageUploadRequest(
        test_result_id=tr.id,
        patient_name="Rafael",
        owner_name="Laura",
        received_at=datetime.now(timezone.utc),
        images=[
            ImageUploadItem(obs_identifier="BACI_Main", base64_data=make_valid_jpeg_base64()),
            ImageUploadItem(obs_identifier="COS_Main", base64_data=make_valid_jpeg_base64()),
            ImageUploadItem(obs_identifier="YEA_Part1", base64_data=make_valid_jpeg_base64()),
            ImageUploadItem(obs_identifier="FECES_Distribution", base64_data=make_valid_jpeg_base64()),
        ],
    )
    result = await service.save_images(request, session)

    assert result.total_saved == 4
    paths = [r["file_path"] for r in result.saved]
    assert any("Bacilos_Main.jpg" in p for p in paths)
    assert any("Cocos_Main.jpg" in p for p in paths)
    assert any("Levaduras_Part1.jpg" in p for p in paths)
    assert any("Heces_Distribution.jpg" in p for p in paths)


@pytest.mark.asyncio
async def test_invalid_base64_goes_to_failed(session, tmp_path):
    tr = await create_test_result_in_db(session)
    service = ImageHandlingService()
    service._base_dir = str(tmp_path)

    request = ImageUploadRequest(
        test_result_id=tr.id,
        patient_name="Kitty",
        owner_name="Laura Cepeda",
        received_at=datetime.now(timezone.utc),
        images=[
            # Truly invalid: contains chars outside base64 alphabet
            ImageUploadItem(obs_identifier="WBC_Main", base64_data="<not-base64-at-all!!!@#$>"),
        ],
    )
    result = await service.save_images(request, session)

    assert result.total_failed == 1
    assert result.total_saved == 0


@pytest.mark.asyncio
async def test_db_records_created_with_correct_metadata(session, tmp_path):
    from sqlmodel import select
    tr = await create_test_result_in_db(session)
    service = ImageHandlingService()
    service._base_dir = str(tmp_path)

    request = ImageUploadRequest(
        test_result_id=tr.id,
        patient_name="Kitty",
        owner_name="Laura Cepeda",
        received_at=datetime.now(timezone.utc),
        images=[
            ImageUploadItem(obs_identifier="WBC_Main", base64_data=make_valid_jpeg_base64()),
            ImageUploadItem(obs_identifier="RBC_Histo", base64_data=make_valid_jpeg_base64()),
        ],
    )
    await service.save_images(request, session)

    result = await session.execute(
        select(PatientImage).where(PatientImage.test_result_id == tr.id)
    )
    db_images = result.scalars().all()
    assert len(db_images) == 2

    names = {img.parameter_name_es for img in db_images}
    assert "Leucocitos" in names
    assert "Eritrocitos" in names

    types = {img.image_type for img in db_images}
    assert "Main" in types
    assert "Histo" in types

    # Full OBX identifier stored in parameter_code
    codes = {img.parameter_code for img in db_images}
    assert "WBC_Main" in codes
    assert "RBC_Histo" in codes
