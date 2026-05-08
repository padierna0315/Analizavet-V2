from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form, Request
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, func
from app.database import get_session
from app.domains.reception.schemas import RawPatientInput, BaulResult, NormalizedPatient
from app.domains.patients.models import Patient
from app.shared.models.test_result import TestResult
from app.domains.reception.service import ReceptionService
from app.tasks.hl7_processor import get_upload_status
import uuid
import json
from datetime import datetime, timezone

import logfire


# Initialize templates
templates = Jinja2Templates(directory="app/templates")

router = APIRouter(prefix="/reception", tags=["Recepción"])
_service = ReceptionService()


@router.post("/receive", response_model=BaulResult)
async def receive_patient(
    body: RawPatientInput,
    session: AsyncSession = Depends(get_session),
):
    """Receive a raw patient string, normalize it, and register in the Baúl.
    
    Returns the patient ID and whether it was newly created.
    
    Example body:
    {
        "raw_string": "kitty felina 2a Laura Cepeda",
        "source": "LIS_OZELLE",
        "received_at": "2026-04-24T10:00:00Z"
    }
    """
    try:
        return await _service.receive(body, session)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/patients", response_model=dict)
async def list_patients(
    session: AsyncSession = Depends(get_session),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    species: str | None = Query(default=None, description="Filtrar por especie: Canino o Felino"),
    owner: str | None = Query(default=None, description="Filtrar por nombre del tutor"),
):
    """List all registered patients with pagination and optional filters."""
    query = select(Patient)
    
    if species:
        query = query.where(Patient.species == species)
    if owner:
        query = query.where(Patient.owner_name.icontains(owner))
    
    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await session.execute(count_query)
    total = total_result.scalar()
    
    # Paginate
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size).order_by(Patient.updated_at.desc())
    result = await session.execute(query)
    patients = result.scalars().all()
    
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
        "patients": [
            {
                "id": p.id,
                "name": p.name,
                "species": p.species,
                "sex": p.sex,
                "age_display": p.age_display,
                "owner_name": p.owner_name,
                "source": p.source,
                "created_at": p.created_at.isoformat(),
                "updated_at": p.updated_at.isoformat(),
            }
            for p in patients
        ],
    }


@router.post("/upload", status_code=202)
async def handle_upload(
    file: UploadFile = File(...), 
    file_type: str = Form(...),
    session: AsyncSession = Depends(get_session) # Keeping for now, might be removed later if not needed
):
    """
    Handle file uploads for Ozelle, Fujifilm, and JSON patient data.
    """
    try:
        file_content = await file.read()
        upload_id = await _service.handle_uploaded_file(file_content, file_type, session)
        
        # Return HTMX response that sets up polling
        html = f'''
        <div id="upload-status" 
             hx-get="/reception/upload/{upload_id}/status"
             hx-trigger="every 2s"
             hx-swap="outerHTML">
          ⏳ Procesando archivo...
        </div>
        '''
        return HTMLResponse(content=html, status_code=202)

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logfire.error(f"Error processing uploaded file: {e}")
        # Make sure to set error status in Redis if this happens before it gets to the actor
        # Although handle_uploaded_file should set it if it raises an error itself
        raise HTTPException(status_code=500, detail="Error processing file")


@router.get("/upload/{upload_id}/status", response_class=HTMLResponse)
async def get_upload_status_endpoint(upload_id: str, request: Request):
    """
    Pollable endpoint to get the status of an HL7 file upload.
    """
    status = get_upload_status(upload_id) # Use the helper function

    if status is None:
        # Not found — show error. This could happen if Redis key expired or upload_id was invalid.
        return HTMLResponse('<div class="upload-error" id="upload-status">❌ Estado no encontrado (o expirado)</div>')
    
    if status == "processing":
        # Still processing — keep polling
        return HTMLResponse(f'''
        <div id="upload-status"
             hx-get="/reception/upload/{upload_id}/status"
             hx-trigger="every 2s"
             hx-swap="outerHTML">
          ⏳ Procesando archivo...
        </div>
        ''')
    
    if status.startswith("complete:"):
        count = status.split(":")[1]
        # Trigger waiting room refresh + show success
        return HTMLResponse(
            f'<div class="upload-success" id="upload-status">✅ {count} paciente(s) cargado(s)</div>',
            headers={"HX-Trigger": "refreshReceptionGrid"}
        )
    
    if status.startswith("error:"):
        msg = status.split(":", 1)[1]
        return HTMLResponse(f'<div class="upload-error" id="upload-status">❌ Error: {msg}</div>')



@router.post("/reception/procesar/{test_result_id}")
async def process_test_result(
    test_result_id: int,
    session: AsyncSession = Depends(get_session),
    request: Request = None,
):
    """Process a test result and move it to the taller."""
    # Get the test result by ID
    statement = select(TestResult).where(TestResult.id == test_result_id)
    result = await session.execute(statement)
    test_result = result.scalar_one_or_none()
    
    if not test_result:
        raise HTTPException(status_code=404, detail="Test result not found")
    
    # Update the status to "pendiente"
    test_result.status = "pendiente"
    session.add(test_result)
    await session.commit()
    
    # Return HTML for HTMX to update the row
    if request:
        return templates.TemplateResponse("recepcion/patient_processed.html", {
            "request": request,
            "test_result": test_result
        })
    else:
        return {"status": "success", "message": "Test result moved to taller"}


@router.get("/recepcion")
async def get_recepcion(request: Request, session: AsyncSession = Depends(get_session)):
    """Display the queue of patients with status="recibido"."""
    # Query for test results with status="recibido" and join with patient data
    query = select(TestResult, Patient).join(Patient).where(TestResult.status == "recibido")
    result = await session.execute(query)
    results = result.all()
    
    # Group test results by patient for display
    patients_data = {}
    for test_result, patient in results:
        if patient.id not in patients_data:
            patients_data[patient.id] = {
                "patient": patient,
                "test_results": []
            }
        patients_data[patient.id]["test_results"].append(test_result)
    
    # Convert to list for template rendering
    patients_list = list(patients_data.values())
    
    return templates.TemplateResponse("recepcion/index.html", {
        "request": request,
        "patients": patients_list
    })


@router.get("/taller/reception", response_class=HTMLResponse)
async def get_taller_reception(
    request: Request, 
    session: AsyncSession = Depends(get_session)
):
    """Endpoint to serve the waiting room (sala de espera) data for the Taller view."""
    patients_data = await _service.get_waiting_room_patients(session)
    
    # For now, return a simple placeholder template that lists patient names
    # This will be replaced with the full grid component in a later task
    return templates.TemplateResponse("taller/reception.html", {
        "request": request,
        "patients": patients_data
    })



@router.get("/close-modal")
async def close_modal():
    return HTMLResponse("")


@router.get("/patient/{patient_id}/confirm-delete", response_class=HTMLResponse)
async def confirm_delete_patient(
    patient_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session)
):
    """Show confirmation dialog for deleting a patient from the waiting room."""
    patient = await session.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    return templates.TemplateResponse(
        "reception/partials/confirm_delete.html",
        {
            "request": request,
            "patient_id": patient_id,
            "patient_name": patient.name
        }
    )


@router.delete("/patient/{patient_id}", status_code=200)
async def delete_patient(
    patient_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Delete a patient from the waiting room."""
    deleted = await _service.delete_patient_from_waiting_room(patient_id, session)
    if not deleted:
        raise HTTPException(status_code=404, detail="Patient not found in waiting room")

    # HTMX OOB pattern:
    # - El elemento principal vacío hace que outerHTML de la tarjeta elimine el nodo
    # - El OOB limpia el modal-container al mismo tiempo
    # Usamos HX-Reswap: delete para eliminar la tarjeta sin dejar rastro
    response = HTMLResponse(
        content='<div id="modal-container" hx-swap-oob="innerHTML"></div>',
        status_code=200
    )
    response.headers["HX-Reswap"] = "delete"
    return response



@router.post("/patient/{patient_id}/inject-to-taller", response_class=HTMLResponse)
async def inject_patient_to_taller(
    patient_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """
    Groups pending/received TestResults for a patient, merges their LabValues
    into a single TestResult, deletes the originals, and loads the result in Taller.
    """
    try:
        unified_test_result = await _service.inject_patient_to_taller(patient_id, session)
        
        if not unified_test_result:
            raise HTTPException(status_code=404, detail="No pending/received test results found for this patient.")

        from app.domains.taller.router import load_patient_workspace
        return await load_patient_workspace(request, unified_test_result.id, session)

    except HTTPException as e:
        raise e
    except Exception as e:
        logfire.error(f"Error injecting patient {patient_id} to Taller: {e}")
        raise HTTPException(status_code=500, detail="Internal server error during Taller injection.")


@router.get("/patient-card/{patient_id}", response_class=HTMLResponse)
async def get_patient_card(
    patient_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Fetch a single patient card to restore it after cancelling a delete."""
    # This requires a new service method to get a single patient's formatted data
    patient_data = await _service.get_single_patient_for_card(patient_id, session)
    if not patient_data:
        # If patient was deleted in another window, return an empty response
        return Response(content="", status_code=200)

    return templates.TemplateResponse(
        "reception/partials/patient_card.html",
        {
            "request": request,
            "patient": patient_data
        }
    )