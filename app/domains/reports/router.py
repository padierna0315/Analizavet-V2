from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession
import unicodedata

from app.database import get_session
from app.domains.reports.service import ReportService
from app.domains.taller.service import TallerService

router = APIRouter(prefix="/reports", tags=["Reportes"])
_report_service = ReportService()
_taller_service = TallerService()


def _sanitize_filename(text: str) -> str:
    nfd = unicodedata.normalize("NFD", text)
    ascii_text = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return ascii_text.replace(" ", "_")


@router.get("/{result_id}/pdf")
async def download_pdf(
    result_id: int,
    session: AsyncSession = Depends(get_session),
):
    data = await _taller_service.get_test_result_full(result_id, session)
    if not data:
        raise HTTPException(status_code=404, detail="Resultado no encontrado")

    patient_name = _sanitize_filename(data["patient"]["name"] or "")
    test_type = _sanitize_filename(data["test_result"]["test_type"] or "")
    date_str = data["test_result"]["received_at"][:10].replace("-", "")
    filename = f"{patient_name}_{date_str}_{test_type}.pdf"

    pdf_bytes = _report_service.generate_pdf_sync(data)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )