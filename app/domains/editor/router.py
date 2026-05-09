import json
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from typing import Optional

from clinical_standards import (
    VETERINARY_STANDARDS,
    PARAMETER_GROUPS,
    JSON_PATH,
    load_standards_from_json,
    reset_to_defaults
)

router = APIRouter(prefix="/modoeditor", tags=["Editor"])
templates = Jinja2Templates(directory="app/templates")

@router.get("/", response_class=HTMLResponse)
async def editor_index(request: Request):
    return templates.TemplateResponse("editor/index.html", {
        "request": request,
        "standards": VETERINARY_STANDARDS,
        "groups": PARAMETER_GROUPS
    })

@router.get("/form/{code}", response_class=HTMLResponse)
async def editor_form(request: Request, code: str):
    param = VETERINARY_STANDARDS.get(code)
    if not param:
        raise HTTPException(status_code=404, detail="Parámetro no encontrado")
    
    return templates.TemplateResponse("editor/form.html", {
        "request": request,
        "code": code,
        "param": param
    })

@router.get("/row/{code}", response_class=HTMLResponse)
async def editor_row(request: Request, code: str):
    param = VETERINARY_STANDARDS.get(code)
    if not param:
        raise HTTPException(status_code=404, detail="Parámetro no encontrado")
    
    return templates.TemplateResponse("editor/row.html", {
        "request": request,
        "code": code,
        "param": param
    })

@router.post("/save/{code}", response_class=HTMLResponse)
async def editor_save(
    request: Request,
    code: str,
    name: str = Form(...),
    unit: str = Form(...),
    canine_min: Optional[float] = Form(None),
    canine_max: Optional[float] = Form(None),
    feline_min: Optional[float] = Form(None),
    feline_max: Optional[float] = Form(None)
):
    if code not in VETERINARY_STANDARDS:
        raise HTTPException(status_code=404, detail="Parámetro no encontrado")

    # Update the data structure
    updated_param = VETERINARY_STANDARDS[code].copy()
    updated_param["name"] = name
    updated_param["unit"] = unit
    updated_param["ranges"] = {
        "canine": {"min": canine_min, "max": canine_max},
        "feline": {"min": feline_min, "max": feline_max}
    }

    # Load all current standards from JSON to ensure we don't overwrite other concurrent changes
    # (Though here we are the only ones)
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        all_standards = json.load(f)
    
    all_standards[code] = updated_param
    
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(all_standards, f, indent=4, ensure_ascii=False)
    
    # Reload in-memory
    load_standards_from_json()
    
    return templates.TemplateResponse("editor/row.html", {
        "request": request,
        "code": code,
        "param": VETERINARY_STANDARDS[code]
    })

@router.post("/reset")
async def editor_reset(request: Request):
    reset_to_defaults()
    return RedirectResponse(url="/modoeditor", status_code=303)
