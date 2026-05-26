from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from babel.dates import format_date, Locale # Added for fecha_es


from app.database import get_session
from app.template_engine import templates
from app.shared.models.patient_image import PatientImage
from app.shared.models.test_result import TestResult
from app.domains.patients.models import Patient
from app.shared.models.doctor import Doctor
from app.domains.taller.schemas import (
    EnrichRequest, FlagBatchResult, FlagBatchRequest, ImageUploadRequest,
    ImageUploadResult, RawLabValueInput,
)
from app.domains.taller.service import TallerService

from app.domains.taller.doctors_router import router as doctors_router

router = APIRouter(prefix="/taller", tags=["Taller"])
router.include_router(doctors_router)
_service = TallerService()


# ── Dashboard Endpoint ───────────────────────────────────────────────────────


@router.get("/", response_class=HTMLResponse)
async def taller_dashboard(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Render the Taller dashboard with adapter status and pending patients.

    This is the main entry point for the Taller view.
    Shows adapter status, reception queue, and quick actions.
    """
    # Get adapter status from the main app
    from app import mllp_state

    adapters = []
    for adapter in mllp_state.adapters:
        adapters.append({
            "name": adapter.get_source_name(),
            "is_running": adapter.is_running(),
            "port": adapter.port,
        })

    # Check for pending patients in reception
    pending_patients = []
    has_pending = False
    reception_status = "No hay pacientes en cola"

    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

        result = await session.execute(
            select(TestResult)
            .where(TestResult.status != "listo")
            .order_by(TestResult.received_at.desc())
            .limit(10)
        )
        recent_tests = result.scalars().all()

        if recent_tests:
            has_pending = True
            reception_status = f"{len(recent_tests)} paciente(s) reciente(s)"

            # Get patient details for each test
            for test in recent_tests:
                patient_result = await session.execute(
                    select(Patient).where(Patient.id == test.patient_id)
                )
                patient = patient_result.scalars().first()
                if patient:
                    pending_patients.append({
                        "test_id": test.id,
                        "patient_id": patient.id,
                        "name": patient.name,
                        "species": patient.species,
                        "owner_name": patient.owner_name,
                        "test_type": test.test_type,
                        "received_at": test.received_at.isoformat() if test.received_at else None,
                    })
    except Exception:
        # If there's any error, just show empty queue
        has_pending = False
        reception_status = "Sistema de cola no disponible"

    # Use shared Jinja2Templates from template_engine
    return templates.TemplateResponse(
        "taller/dashboard.html",
        {
            "request": request,
            "adapters": adapters,
            "has_pending_patients": has_pending,
            "pending_patients": pending_patients,
            "reception_status": reception_status,
        },
    )


@router.post("/enrich", response_model=dict)
async def enrich_test_result(
    body: EnrichRequest,
    session: AsyncSession = Depends(get_session),
):
    """Create a TestResult, flag all lab values, store everything.

    Full pipeline:
    1. Create TestResult record
    2. Flag all values (ALTO/NORMAL/BAJO)
    3. Store LabValue rows
    4. Return enriched result with summary

    Example body:
    {
        "patient_id": 1,
        "species": "Felino",
        "test_type": "Hemograma",
        "test_type_code": "CBC",
        "source": "LIS_OZELLE",
        "received_at": "2026-04-24T10:00:00Z",
        "values": [
            {"parameter_code": "WBC", "parameter_name_es": "Leucocitos",
             "raw_value": "14.26", "numeric_value": 14.26,
             "unit": "10*9/L", "reference_range": "5.05-16.76"}
        ]
    }
    """
    try:
        # Create TestResult
        tr = await _service.create_test_result(
            patient_id=body.patient_id,
            test_type=body.test_type,
            test_type_code=body.test_type_code,
            source=body.source,
            received_at=body.received_at,
            session=session,
        )

        # Flag and store
        flag_result = await _service.flag_and_store(
            test_result_id=tr.id,
            species=body.species,
            values=body.values,
            session=session,
        )

        return {
            "test_result_id": tr.id,
            "patient_id": body.patient_id,
            "status": flag_result.status,
            "summary": flag_result.summary,
            "total_values": len(flag_result.flagged_values),
        }

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/results/{result_id}", response_model=dict)
async def get_test_result(
    result_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Get full TestResult with all LabValues, images, and patient info."""
    data = await _service.get_test_result_full(result_id, session)
    if not data:
        raise HTTPException(
            status_code=404,
            detail=f"TestResult con ID {result_id} no encontrado"
        )
    return data


@router.get("/preview/{result_id}", response_class=HTMLResponse)
async def get_preview_get(
    request: Request, # Added request here
    result_id: int,
    session: AsyncSession = Depends(get_session),
):
    """GET /taller/preview/{id} — returns initial preview HTML (server-rendered, no form data).

    Used for: initial page load and backward-compatibility with existing tests.
    For live HTMX updates, use POST /taller/preview/{id}.
    """
    data = await _service.get_test_result_full(result_id, session)
    if not data:
        return HTMLResponse(
            content="<p class='preview-error'>Resultado no encontrado</p>",
            status_code=404,
        )
    return HTMLResponse(content=_render_preview_html(data, request)) # Pass request here


@router.post("/preview/{result_id}", response_class=HTMLResponse)
async def get_preview_post(
    request: Request,
    result_id: int,
    session: AsyncSession = Depends(get_session),
):
    """HTMX endpoint: recalculate flags from form data, return preview HTML.

    Called by HTMX whenever the user changes a value in the lab table.
    Parses form data, recalculates ALTO/BAJO/NORMAL flags, returns updated preview.
    """
    # 1. Get current TestResult + Patient from DB
    data = await _service.get_test_result_full(result_id, session)
    if not data:
        return HTMLResponse(
            content="<p class='preview-error'>Resultado no encontrado</p>",
            status_code=404,
        )

    patient = data.get("patient") or {}
    tr = data["test_result"]
    lab_values_from_db = data["lab_values"]

    # 2. Leer form data PRIMERO — todo lo demás depende de esto
    form_data = await request.form()

    # Actualizar datos del paciente si cambiaron
    patient_id = patient.get("id")
    if patient_id:
        patient_obj = await session.get(Patient, patient_id)
        if patient_obj:
            new_name = form_data.get("patient_name")
            new_owner = form_data.get("owner_name")
            new_age = form_data.get("age_display")
            new_breed = form_data.get("breed")

            if new_name: patient_obj.name = new_name
            if new_owner: patient_obj.owner_name = new_owner
            if new_age: patient_obj.age_display = new_age
            if new_breed: patient_obj.breed = new_breed

            session.add(patient_obj)
            await session.commit()
            await session.refresh(patient_obj)
            # Reconstruir dict del paciente con valores actualizados
            patient = {
                "id": patient_obj.id,
                "name": patient_obj.name,
                "species": patient_obj.species,
                "sex": patient_obj.sex,
                "age_display": patient_obj.age_display,
                "owner_name": patient_obj.owner_name,
                "breed": getattr(patient_obj, "breed", "Mestizo"),
            }

    # Actualizar metadata del TestResult (doctor_name, test_type, copro_*, cito_*)
    tr_obj = await session.get(TestResult, result_id)
    if tr_obj:
        doctor_name = form_data.get("doctor_name")
        if doctor_name is not None:
            tr_obj.doctor_name = doctor_name or None
        # Actualizar test_type (título del PDF) si el usuario lo cambió manualmente
        new_test_type = form_data.get("test_type")
        if new_test_type is not None and new_test_type.strip():
            tr_obj.test_type = new_test_type.strip()
            # Mapear test_type_code según el nuevo test_type cuando sea posible
            _test_type_code_map = {
                "Perfil Básico": "CHEM",
                "Perfil Renal": "CHEM",
                "Perfil Hepático": "CHEM",
                "Coprológico": "COPROSC",
                "Coprológico Seriado 1": "COPROSC",
                "Coprológico Seriado 2": "COPROSC",
                "Coprológico Seriado 3": "COPROSC",
                "Citoquímico": "CITO",
            }
            if new_test_type.strip() in _test_type_code_map:
                tr_obj.test_type_code = _test_type_code_map[new_test_type.strip()]
        for field in ["copro_color","copro_consistencia","copro_olor","cito_color","cito_turbidez","cito_aspecto"]:
            val = form_data.get(field)
            if val is not None:
                setattr(tr_obj, field, val or None)
        moco_val = form_data.get("copro_moco")
        if moco_val is not None:
            tr_obj.copro_moco = True if moco_val == "true" else (False if moco_val == "false" else None)
        session.add(tr_obj)
        await session.commit()
        await session.refresh(tr_obj)
        tr = tr_obj.model_dump() if hasattr(tr_obj, "model_dump") else tr
    # 3. Guardar los valores de laboratorio en la BD (El taller es la verdad absoluta)
    await _service.update_lab_values_from_form(result_id, form_data, session)

    # 4. Refetch all updated data to guarantee exact match with DB
    data = await _service.get_test_result_full(result_id, session)

    # 5. Render preview HTML using the unified function
    return HTMLResponse(content=_render_preview_html(data, request))





@router.post("/images", response_model=ImageUploadResult)
async def upload_images(
    body: ImageUploadRequest,
    session: AsyncSession = Depends(get_session),
):
    """Upload Base64 images for a TestResult.

    Each image uses the full Ozelle OBX identifier as obs_identifier.
    Example: "WBC_Main", "LYM_Part3", "PLT_Histo"

    Images are saved to disk in:
        images/{PatientName}_{OwnerName}/{YYYYMMDD}/{SpanishName}_{Type}.jpg
    """
    try:
        return await _service.save_images(body, session)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error guardando imágenes: {e}")


# ── Algorithm & Image toggle endpoints ─────────────────────────────────────────


def _render_algorithm_errors(errors: list[dict]) -> str:
    """Render the 'Diagnóstico del Motor' panel HTML using template."""
    if not errors:
        return ""
    return templates.get_template("taller/partials/algorithm_errors.html").render(
        errors=errors,
    )


def _render_preview_html(data: dict, request: Request) -> str:
    """Render the right-panel preview HTML with patient, summary, and lab values."""
    # Format date for 'fecha_es'
    test_result = data["test_result"]
    received_at = test_result["received_at"]
    if isinstance(received_at, str):
        dt_object = datetime.fromisoformat(received_at)
    elif isinstance(received_at, datetime):
        dt_object = received_at
    else:
        dt_object = datetime.now()
    fecha_es = format_date(dt_object, format='full', locale='es')

    data["fecha_es"] = fecha_es  # Add fecha_es to the data dictionary
    data["request"] = request    # Add request to the data dictionary
    data["dt_received_at"] = dt_object # Add datetime object for template formatting

    return templates.get_template("report/report.html").render(**data)



@router.patch("/images/{image_id}/toggle", response_class=HTMLResponse)
async def toggle_image(
    request: Request,
    image_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Toggle is_included_in_report and trigger preview refresh via HTMX event."""
    img_result = await session.execute(
        select(PatientImage).where(PatientImage.id == image_id)
    )
    img = img_result.scalars().first()
    if not img:
        raise HTTPException(status_code=404, detail="Imagen no encontrada")

    img.is_included_in_report = not img.is_included_in_report
    session.add(img)
    await session.commit()

    checked = "checked" if img.is_included_in_report else ""
    html = templates.get_template("taller/partials/image_toggle.html").render(
        image_id=img.id,
        checked=checked,
    )
    headers = {"HX-Trigger": "updatePreview"}
    return HTMLResponse(content=html, headers=headers)


# ── Dashboard HTMX Endpoints ─────────────────────────────────────────────────


@router.get("/pending-patients", response_class=HTMLResponse)
async def get_pending_patients_fragment(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """HTMX endpoint: return pending patients list HTML for dashboard."""

    result = await session.execute(
        select(TestResult)
        .where(TestResult.status != "listo")
        .order_by(TestResult.received_at.desc())
        .limit(10)
    )
    recent_tests = result.scalars().all()

    patients_list = []
    for test in recent_tests:
        patient_result = await session.execute(
            select(Patient).where(Patient.id == test.patient_id)
        )
        patient = patient_result.scalars().first()
        if patient:
            patients_list.append({
                "test_id": test.id,
                "patient_id": patient.id,
                "name": patient.name,
                "species": patient.species,
                "owner_name": patient.owner_name,
                "test_type": test.test_type,
            })

    # Render just the list HTML using template
    html_content = templates.get_template("taller/partials/pending_patients.html").render(
        patients=patients_list,
    )
    return HTMLResponse(content=html_content)


@router.post("/load-patient/{result_id}", response_class=HTMLResponse)
async def load_patient_workspace(
    request: Request,
    result_id: int,
    session: AsyncSession = Depends(get_session),
):
    """HTMX endpoint: load patient workspace (two columns) into dashboard."""
    data = await _service.get_test_result_full(result_id, session)
    if not data:
        return HTMLResponse(
            content="<div class='preview-error'>Paciente no encontrado</div>",
            status_code=404
        )

    # Extract nested data from the service response
    test_result = data.get("test_result", {})
    lab_values = data.get("lab_values", [])
    patient = data.get("patient", {})

    # Fetch doctors for the dropdown
    _doctors_result = await session.execute(select(Doctor))
    doctors = _doctors_result.scalars().all()

    # Build doctors context for template
    doctor_list = [{"id": d.id, "name": d.name} for d in doctors]
    current_doctor = test_result.get("doctor_name", "") or ""

    # Pre-process lab values to ensure all fields are strings for template
    lab_values_for_template = []
    for lv in lab_values:
        lab_values_for_template.append({
            "parameter_code": str(lv.get("parameter_code", "")),
            "parameter_name_es": str(lv.get("parameter_name_es", "")),
            "raw_value": str(lv.get("raw_value", "")),
            "unit": str(lv.get("unit", "")),
            "reference_range": str(lv.get("reference_range", "")),
            "flag": str(lv.get("flag", "NORMAL")),
        })

    # Render the two-column workspace HTML via template
    html_content = templates.get_template("taller/partials/workspace.html").render(
        result_id=result_id,
        patient={
            "name": patient.get("name") or "",
            "species": patient.get("species") or "",
            "sex": patient.get("sex") or "",
            "age_display": patient.get("age_display") or "",
            "owner_name": patient.get("owner_name") or "",
            "breed": patient.get("breed") or "Mestizo",
        },
        test_result={
            "test_type": test_result.get("test_type", ""),
        },
        lab_values=lab_values_for_template,
        doctors=doctor_list,
        current_doctor=current_doctor,
    )
    return HTMLResponse(content=html_content)


@router.delete("/pending-patient/{patient_id}", response_class=HTMLResponse)
async def delete_pending_patient(
    request: Request,
    patient_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Remove patient from pending queue (mark as processed)."""
    # In a real implementation, this would update the queue
    # For now, we just return an empty response which removes the element
    return HTMLResponse(content="")
