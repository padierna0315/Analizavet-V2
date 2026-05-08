from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import HTMLResponse
import jinja2
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, func

from app.database import get_session
from app.domains.patients.models import Patient
from app.shared.models.test_result import TestResult

router = APIRouter(prefix="/patients", tags=["UI Pacientes"])
_patients_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader("app/templates"),
    autoescape=jinja2.select_autoescape(),
)


@router.get("", response_class=HTMLResponse)
async def list_patients_page(
    request: Request,
    session: AsyncSession = Depends(get_session),
    page: int = Query(1, ge=1),
    search: str = Query("", description="Buscar por nombre o tutor"),
):
    """HTML page listing patients."""
    page_size = 20

    query = select(Patient)
    if search:
        search_term = f"%{search}%"
        # Search by patient name or owner name
        query = query.where(
            (Patient.name.icontains(search_term)) |
            (Patient.owner_name.icontains(search_term))
        )

    # Order by newest
    query = query.order_by(Patient.updated_at.desc())

    # Pagination
    offset = (page - 1) * page_size
    paginated_query = query.offset(offset).limit(page_size)

    result = await session.execute(paginated_query)
    patients = result.scalars().all()

    # Check if this is an HTMX request for pagination/search
    is_htmx = "hx-request" in request.headers

    template_name = "patients/list_fragment.html" if is_htmx else "patients/index.html"

    template = _patients_env.get_template(template_name)
    html = template.render(
        request=request,
        patients=patients,
        search=search,
        page=page,
        next_page=page + 1 if len(patients) == page_size else None
    )
    return HTMLResponse(content=html)


@router.get("/{patient_id}", response_class=HTMLResponse)
async def patient_detail_page(
    request: Request,
    patient_id: int,
    session: AsyncSession = Depends(get_session),
):
    """HTML page showing patient details and their test history."""

    # Get patient
    p_result = await session.execute(select(Patient).where(Patient.id == patient_id))
    patient = p_result.scalars().first()
    if not patient:
        raise HTTPException(status_code=404, detail="Paciente no encontrado")

    # Get test history
    tr_result = await session.execute(
        select(TestResult)
        .where(TestResult.patient_id == patient_id)
        .order_by(TestResult.received_at.desc())
    )
    test_results = tr_result.scalars().all()

    template = _patients_env.get_template("patients/detail.html")
    html = template.render(
        request=request,
        patient=patient,
        test_results=test_results,
    )
    return HTMLResponse(content=html)