from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession
import unicodedata

from app.database import get_session
from app.domains.reports.service import ReportService
from app.domains.taller.service import TallerService

router = APIRouter(prefix="/reports", tags=["Reportes"])
_report_service = ReportService()
_taller_service = TallerService()


def _sanitize_patient_name(text: str) -> str:
    """Sanitize a patient name for use in filenames.

    - Lowercases the text
    - Strips Unicode accents (NFD normalization)
    - Replaces spaces with underscores
    - Removes any character that is not alphanumeric, underscore, hyphen, or dot
    """
    nfd = unicodedata.normalize("NFD", text)
    ascii_text = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    ascii_text = ascii_text.lower().replace(" ", "_")
    return "".join(c for c in ascii_text if c.isalnum() or c in "_-.")


def _sanitize_person_name(text: str) -> str:
    """Sanitize a person name (owner, doctor) for use in filenames.

    - Strips Unicode accents (NFD normalization)
    - Preserves spaces and most printable characters
    - Removes any character that is not alphanumeric, space, underscore, hyphen, or dot
    """
    nfd = unicodedata.normalize("NFD", text)
    ascii_text = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return "".join(c for c in ascii_text if c.isalnum() or c in " _-.")


@router.get("/{result_id}/pdf")
async def download_pdf(
    result_id: int,
    session: AsyncSession = Depends(get_session),
):
    data = await _taller_service.get_test_result_full(result_id, session)
    if not data:
        raise HTTPException(status_code=404, detail="Resultado no encontrado")

    patient_name = _sanitize_patient_name(data["patient"]["name"] or "")
    owner_name_raw = (data["patient"]["owner_name"] or "").strip()
    owner_name = _sanitize_person_name(owner_name_raw) if owner_name_raw else "Sin_tutor"
    doctor_name_raw = (data["test_result"].get("doctor_name") or "").strip()
    if not doctor_name_raw:
        doctor_name_raw = (data["patient"].get("doctor_name") or "").strip()
    doctor_name = _sanitize_person_name(doctor_name_raw) if doctor_name_raw else "Sin_medico"
    filename = f"{patient_name}-{owner_name}-{doctor_name}.pdf"

    pdf_bytes = _report_service.generate_pdf_sync(data)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )