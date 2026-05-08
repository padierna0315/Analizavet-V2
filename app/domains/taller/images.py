import base64
import re
import unicodedata
from datetime import datetime
from pathlib import Path

import logfire
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.shared.models.patient_image import PatientImage
from app.shared.models.test_result import TestResult
from app.domains.taller.schemas import ImageUploadRequest, ImageUploadResult
from app.config import settings
from app.domains.taller.triage import seleccionar_mejores_imagenes


from clinical_standards import get_parameter_name

# Suffixes used by Ozelle in OBX identifiers (confirmed from real log)
_KNOWN_SUFFIXES = {"Main", "Histo", "Distribution"}
_PART_PATTERN = re.compile(r"_Part(\d+)$")


def _parse_obs_identifier(obs_id: str) -> tuple[str, str]:
    """Parse Ozelle OBX identifier into (base_code, suffix).

    Examples:
        "WBC_Main"             → ("WBC", "Main")
        "LYM_Part3"            → ("LYM", "Part3")
        "PLT_Histo"            → ("PLT", "Histo")
        "RBC_PLT_Distribution" → ("RBC_PLT", "Distribution")
        "P-LCC_Main"           → ("P-LCC", "Main")
        "FECES_Distribution"   → ("FECES", "Distribution")
    """
    # Check for _PartN suffix first
    part_match = _PART_PATTERN.search(obs_id)
    if part_match:
        suffix = f"Part{part_match.group(1)}"
        base = obs_id[:part_match.start()]
        return base, suffix

    # Check for known word suffixes (_Main, _Histo, _Distribution)
    for suffix in _KNOWN_SUFFIXES:
        if obs_id.endswith(f"_{suffix}"):
            base = obs_id[:-(len(suffix) + 1)]
            return base, suffix

    # No known suffix — return full identifier as base, no suffix
    return obs_id, ""


def _translate_base_code(base_code: str) -> str:
    """Translate image base code to Spanish name.
    Falls back to lowercase code with warning if not found.
    """
    code_key = base_code.split('/')[0] if '/' in base_code else base_code
    param_name = get_parameter_name(code_key, short=True)
    if param_name == code_key.lower(): # Fallback occurred
        logfire.warning(
            f"Código de imagen desconocido: '{base_code}'. "
            f"Verificar en clinical_standards.py."
        )
    return param_name


def _build_filename(obs_identifier: str) -> tuple[str, str]:
    """Parse OBX identifier and build Spanish filename.

    Returns (filename, parameter_name_es).

    Examples:
        "WBC_Main"             → ("Leucocitos_Main.jpg", "Leucocitos")
        "LYM_Part3"            → ("Linfocitos_Part3.jpg", "Linfocitos")
        "PLT_Histo"            → ("Plaquetas_Histo.jpg", "Plaquetas")
        "RBC_PLT_Distribution" → ("Distribucion_RBC_PLT_Distribution.jpg", "Distribucion_RBC_PLT")
        "BACI_Main"            → ("Bacterias_Main.jpg", "Bacterias")
    """
    base_code, suffix = _parse_obs_identifier(obs_identifier)
    name_es = _translate_base_code(base_code)
    if suffix:
        return f"{name_es}_{suffix}.jpg", name_es
    return f"{name_es}.jpg", name_es


def _sanitize_folder_name(text: str) -> str:
    """Remove accents and spaces for safe folder/file names.

    'Laura Cepeda'  → 'LauraCepeda'
    'niña'          → 'Nina'
    'Señora Ríos'   → 'SenoraRios'

    Better than Ozelle's approach (ni_a, Se_ora_R_os).
    """
    nfd = unicodedata.normalize("NFD", text)
    ascii_text = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return ascii_text.replace(" ", "")


def _build_patient_folder(
    patient_name: str,
    owner_name: str,
    received_at: datetime,
    base_dir: str,
) -> Path:
    """Build the patient-specific folder path.

    Pattern: {base_dir}/{PatientName}_{OwnerName}/{YYYYMMDD}/
    Example: images/Kitty_LauraCepeda/20260424/
    """
    safe_patient = _sanitize_folder_name(patient_name)
    safe_owner = _sanitize_folder_name(owner_name)
    date_str = received_at.strftime("%Y%m%d")
    folder = Path(base_dir) / f"{safe_patient}_{safe_owner}" / date_str
    return folder


class ImageHandlingService:
    """Handles saving of histogram images from satellites.

    Images are stored on disk, NOT in the database.
    The database only stores the file path + metadata.

    Folder structure:
        images/{PatientName}_{OwnerName}/{YYYYMMDD}/{ParameterNameEs}_{Suffix}.jpg

    Examples:
        images/Kitty_LauraCepeda/20260424/Leucocitos_Main.jpg
        images/Kitty_LauraCepeda/20260424/Linfocitos_Part3.jpg
        images/Kitty_LauraCepeda/20260424/Plaquetas_Histo.jpg
        images/Rafael_Laura/20260424/Bacterias_Main.jpg  ← coproscópico
    """

    def __init__(self):
        self._base_dir = getattr(settings, "IMAGES_DIR", "./images")

    async def save_images(
        self,
        request: ImageUploadRequest,
        session: AsyncSession,
    ) -> ImageUploadResult:
        """Decode Base64 images and save to disk + DB."""

        # ── Valida que el TestResult exista antes de procesar imágenes ────────
        result_check = await session.get(TestResult, request.test_result_id)
        if not result_check:
            raise ValueError(
                f"TestResult {request.test_result_id} no encontrado. "
                f"No se pueden asociar imágenes a un registro inexistente."
            )

        # ── Prepara carpeta del paciente ──────────────────────────────────────
        patient_folder = _build_patient_folder(
            request.patient_name,
            request.owner_name,
            request.received_at,
            self._base_dir,
        )
        patient_folder.mkdir(parents=True, exist_ok=True)

        saved: list[dict] = []
        failed: list[dict] = []
        # Lista de archivos creados en disco (para limpieza si falla commit)
        created_files: list[Path] = []
        # Track obs_identifiers seen in this batch to detect duplicates
        seen_identifiers: set[str] = set()

        for image_item in request.images:
            # Detect duplicate obs_identifier in same batch
            if image_item.obs_identifier in seen_identifiers:
                logfire.warning(
                    f"obs_identifier duplicado en el batch: '{image_item.obs_identifier}'. "
                    f"Se omite para evitar sobrescritura silenciosa."
                )
                failed.append({
                    "obs_identifier": image_item.obs_identifier,
                    "error": f"obs_identifier duplicado en el batch: '{image_item.obs_identifier}'",
                })
                continue
            seen_identifiers.add(image_item.obs_identifier)

            try:
                filename, name_es = _build_filename(image_item.obs_identifier)
                _, suffix = _parse_obs_identifier(image_item.obs_identifier)
                base_code, _ = _parse_obs_identifier(image_item.obs_identifier)

                image_data = self._decode_base64(image_item.base64_data)
                file_path = patient_folder / filename

                # Detect if file already exists (cross-batch overwrite protection)
                if file_path.exists():
                    logfire.warning(
                        f"Archivo ya existe: {file_path}. "
                        f"Se sobrescribe — verificar si es intencional."
                    )

                file_path.write_bytes(image_data)
                created_files.append(file_path)

                db_image = PatientImage(
                    test_result_id=request.test_result_id,
                    parameter_code=image_item.obs_identifier,   # full: "WBC_Main"
                    parameter_name_es=name_es,                  # "Leucocitos"
                    file_path=str(file_path),
                    patient_folder=str(patient_folder),
                    image_type=suffix or "unknown",             # "Main", "Part3", etc.
                    file_size_bytes=len(image_data),
                )
                session.add(db_image)

                saved.append({
                    "obs_identifier": image_item.obs_identifier,
                    "parameter_name_es": name_es,
                    "file_path": str(file_path),
                })
                logfire.debug(f"Imagen guardada: {file_path}")

            except Exception as e:
                logfire.error(
                    f"Error guardando imagen para "
                    f"{image_item.obs_identifier}: {e}"
                )
                failed.append({
                    "obs_identifier": image_item.obs_identifier,
                    "error": str(e),
                })

        # ── Commit de registros en DB ────────────────────────────────────────
        # Si hubo imágenes válidas (saved), intentamos persistir.
        # Si el commit falla (ej. FK violation, constraint), revertimos
        # los archivos creados para evitar inconsistencias disco/DB.
        if saved:
            try:
                await session.commit()
                logfire.info(
                    f"Commit ejecutado. Imágenes TestResult {request.test_result_id}: "
                    f"{len(saved)} guardadas, {len(failed)} fallidas"
                )
            except Exception as commit_err:
                # Rollback de la sesión para dejarla en estado limpio
                await session.rollback()
                # Borrar archivos creados (rollback compensatorio)
                for fpath in created_files:
                    try:
                        fpath.unlink(missing_ok=True)
                        logfire.warning(f"Rollback: archivo eliminado {fpath}")
                    except Exception as del_err:
                        logfire.error(f"No se pudo eliminar {fpath} tras rollback: {del_err}")
                raise ValueError(
                    f"Fallo al persistir imágenes en la base de datos: {commit_err}. "
                    f"Archivos en disco han sido revertidos."
                ) from commit_err
        elif failed:
            # No había imágenes válidas para guardar, pero hubo errores.
            # No hay commit necesario (no se añadió nada a la sesión).
            logfire.info(
                f"Ninguna imagen válida para TestResult {request.test_result_id}. "
                f"{len(failed)} fallidas."
            )
        else:
            # No images in request
            logfire.info(f"No images to process for TestResult {request.test_result_id}")

        # ── Aplicar triage SOLO si hubo imágenes guardadas (DB + disco) ─────
        # El triage necesita IDs reales (post-commit) para referenciar correctamente
        if saved:
            all_images = await session.execute(
                select(PatientImage).where(
                    PatientImage.test_result_id == request.test_result_id
                )
            )
            img_list = list(all_images.scalars().all())
            seleccionar_mejores_imagenes(img_list)
            for img in img_list:
                session.add(img)
            await session.commit()
            logfire.debug(f"Triage aplicado a {len(img_list)} imágenes")

        return ImageUploadResult(
            test_result_id=request.test_result_id,
            saved=saved,
            failed=failed,
            total_saved=len(saved),
            total_failed=len(failed),
        )

    def _decode_base64(self, data: str) -> bytes:
        """Decode Base64 string to bytes. Handles padding issues."""
        data = data.strip()
        if data.startswith("data:"):
            data = data.split(",", 1)[1]
        missing_padding = len(data) % 4
        if missing_padding:
            data += "=" * (4 - missing_padding)
        try:
            return base64.b64decode(data, validate=True)
        except Exception as e:
            raise ValueError(f"Base64 inválido: {e}")