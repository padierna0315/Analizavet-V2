import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, delete
import unicodedata
import logfire

from app.database import get_session
from app.domains.reports.service import ReportService
from app.domains.taller.service import TallerService
from app.domains.patients.models import Patient
from app.domains.exam_order.models import ExamOrder
from app.domains.jornada.service import append_to_jornada_log
from app.shared.models.patient_archive import PatientArchive
from app.shared.models.raw_data_log import RawDataLog
from app.shared.models.patient_image import PatientImage
from app.shared.models.test_result import TestResult

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

    # ── Retirement: archive patient data + cascade delete ──────────────
    patient_id = data["patient"]["id"]
    patient_name_display = data["patient"]["name"]
    owner_name_display = data["patient"]["owner_name"]
    species = data["patient"]["species"]
    session_code = data["patient"].get("session_code")

    # Phase 1: Archive — include RawDataLog provenance in snapshot
    try:
        # Fetch RawDataLog rows for this patient before retiring
        raw_logs_stmt = (
            select(RawDataLog)
            .where(RawDataLog.patient_id == patient_id)
            .order_by(RawDataLog.received_at.desc())
        )
        raw_logs_result = await session.execute(raw_logs_stmt)
        raw_logs = raw_logs_result.scalars().all()

        raw_data_logs_list = []
        for rl in raw_logs:
            raw_data_logs_list.append({
                "id": rl.id,
                "source": rl.source,
                "raw_data": rl.raw_data,
                "received_at": rl.received_at.isoformat() if rl.received_at else None,
                "captured_at": rl.captured_at.isoformat() if rl.captured_at else None,
                "processed_at": rl.processed_at.isoformat() if rl.processed_at else None,
                "session_code": rl.session_code,
                "status": rl.status,
            })

        # Enrich the snapshot with raw data provenance
        data_with_provenance = dict(data)
        data_with_provenance["raw_data_logs"] = raw_data_logs_list

        snapshot_json = json.dumps(data_with_provenance, default=str, ensure_ascii=False)
        archive = PatientArchive(
            session_code=session_code,
            patient_name=patient_name_display,
            owner_name=owner_name_display,
            species=species,
            snapshot_data=snapshot_json,
            original_patient_id=patient_id,
            original_test_result_id=result_id,
        )
        session.add(archive)
        await session.flush()  # Ensure archive gets an ID, catch constraint errors early

        # Phase 2: Cleanup image files from disk before DB cascade
        img_stmt = (
            select(PatientImage)
            .join(TestResult)
            .where(TestResult.patient_id == patient_id)
        )
        img_result = await session.execute(img_stmt)
        images = img_result.scalars().all()
        for img in images:
            if img.file_path:
                try:
                    Path(img.file_path).unlink(missing_ok=True)
                except Exception as e:
                    logfire.warning(f"Failed to delete image file {img.file_path}: {e}")

        # Phase 3: Delete ExamOrders (no cascade from Patient→ExamOrder)
        await session.execute(delete(ExamOrder).where(ExamOrder.patient_id == patient_id))

        # Phase 4: Delete Patient (ORM cascade deletes TestResults → LabValues + Images)
        patient = await session.get(Patient, patient_id)
        if patient:
            await session.delete(patient)

        await session.commit()

        logfire.info(
            f"Patient {patient_name_display} (id={patient_id}) archived and retired. "
            f"Archive id={archive.id}"
        )

        # ── SIMPLE JORNADA LOG: append minimal entry ──────────────────
        # This is the ONLY place where jornada data is written.
        # The resumen endpoint reads this file, formats the report, and clears it.
        append_to_jornada_log({
            "name": patient_name_display,
            "species": species,
            "owner": owner_name_display,
            "doctor": doctor_name_raw or "Sin médico",
            "test_type": data.get("test_result", {}).get("test_type") or "Examen",
            "test_type_code": data.get("test_result", {}).get("test_type_code") or "",
        })
    except Exception as e:
        await session.rollback()
        logfire.error(
            f"Failed to archive patient {patient_name_display} (id={patient_id}): {e}. "
            f"PDF was generated but patient was NOT deleted."
        )
        # PDF still returned — patient stays in DB

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.get("/archive/{archive_id}/pdf")
async def download_archive_pdf(
    archive_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Regenerate a PDF from an archived patient snapshot."""
    archive = await session.get(PatientArchive, archive_id)
    if not archive:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")

    try:
        data = json.loads(archive.snapshot_data)
    except (json.JSONDecodeError, TypeError) as e:
        logfire.error(f"Corrupted snapshot_data in PatientArchive id={archive_id}: {e}")
        raise HTTPException(status_code=500, detail="Datos del archivo corruptos")

    pdf_bytes = _report_service.generate_pdf_sync(data)

    patient_name = _sanitize_patient_name(data["patient"].get("name") or "")
    owner_name_raw = (data["patient"].get("owner_name") or "").strip()
    owner_name = _sanitize_person_name(owner_name_raw) if owner_name_raw else "Sin_tutor"
    doctor_name_raw = (data.get("test_result", {}).get("doctor_name") or "").strip()
    if not doctor_name_raw:
        doctor_name_raw = (data.get("patient", {}).get("doctor_name") or "").strip()
    doctor_name = _sanitize_person_name(doctor_name_raw) if doctor_name_raw else "Sin_medico"
    filename = f"{patient_name}-{owner_name}-{doctor_name}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
