from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from app.database import get_session
from app.shared.models.doctor import Doctor
from app.template_engine import templates
from fastapi.responses import HTMLResponse
import logfire

router = APIRouter(prefix="/doctors", tags=["doctors"])


def _build_options(doctors: list, selected_name: str = "") -> str:
    return templates.get_template("taller/doctors/partials/doctor_options.html").render(
        doctors=[{"id": d.id, "name": d.name} for d in doctors],
        selected_name=selected_name,
    )


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
    return templates.get_template("taller/doctors/partials/add_doctor_form.html").render()
