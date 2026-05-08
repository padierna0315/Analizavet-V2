from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from app.database import get_session
from app.shared.models.doctor import Doctor
from fastapi.responses import HTMLResponse
import logfire

router = APIRouter(prefix="/doctors", tags=["doctors"])


def _build_options(doctors: list, selected_name: str = "") -> str:
    html = '<option value="">-- Seleccionar médico --</option>'
    for d in doctors:
        sel = "selected" if d.name == selected_name else ""
        html += f'<option value="{d.name}" {sel}>{d.name}</option>'
    return html


@router.get("/", response_class=HTMLResponse)
async def get_doctors_options(session: AsyncSession = Depends(get_session)):
    logfire.info("Fetching all doctors for options")
    result = await session.execute(select(Doctor))
    doctors = result.scalars().all()
    return _build_options(doctors)


@router.post("/", response_class=HTMLResponse)
async def create_doctor(
    name: str = Form(...),
    specialty: Optional[str] = Form(None),
    session: AsyncSession = Depends(get_session),
):
    logfire.info("Creating new doctor", name=name, specialty=specialty)
    new_doctor = Doctor(name=name, specialty=specialty)
    session.add(new_doctor)
    await session.commit()
    await session.refresh(new_doctor)
    result = await session.execute(select(Doctor))
    doctors = result.scalars().all()
    return _build_options(doctors, selected_name=new_doctor.name)


@router.delete("/{doctor_id}", response_class=HTMLResponse)
async def delete_doctor(
    doctor_id: int,
    session: AsyncSession = Depends(get_session),
):
    logfire.info("Deleting doctor", doctor_id=doctor_id)
    doctor = await session.get(Doctor, doctor_id)
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor no encontrado")
    await session.delete(doctor)
    await session.commit()
    result = await session.execute(select(Doctor))
    doctors = result.scalars().all()
    return _build_options(doctors)

@router.get("/form-add", response_class=HTMLResponse)
async def get_add_doctor_form():
    return """
    <div id="doctor-modal-content" class="modal-content">
        <form hx-post="/taller/doctors/" hx-target="#doctor-select" hx-swap="innerHTML"
              hx-indicator="find button[type=submit]"
              hx-disabled-elt="find button[type=submit]">
            <h3>Agregar Nuevo Médico</h3>
            <label for="doctor_name">Nombre:</label>
            <input type="text" name="name" required>
            <label for="doctor_specialty">Especialidad (opcional):</label>
            <input type="text" name="specialty">
            <div style="display:flex; gap:0.5rem; margin-top:0.75rem;">
              <button type="submit"
                      style="padding:0.4rem 1rem; background:#2c5f2e; color:white; border:none; border-radius:6px; cursor:pointer; font-weight:600;">
                Guardar
              </button>
              <button type="button"
                      hx-get="/reception/close-modal"
                      hx-target="#doctor-modal"
                      hx-swap="innerHTML"
                      style="padding:0.4rem 1rem; background:#e5e7eb; border:none; border-radius:6px; cursor:pointer;">
                Cancelar
              </button>
            </div>
        </form>
    </div>
    """
