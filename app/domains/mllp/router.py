from fastapi import APIRouter, HTTPException, status, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import logfire

import app.mllp_state as mllp_state

router = APIRouter(prefix="/api/mllp", tags=["MLLP Control"])
templates = Jinja2Templates(directory="app/templates")


@router.post("/start", status_code=status.HTTP_200_OK)
async def start_mllp_adapters(request: Request):
    if mllp_state.running:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Las máquinas ya están conectadas.",
        )

    logfire.info("Arrancando adaptadores MLLP desde UI...")
    try:
        if not mllp_state.adapters:
            from app.satellites.ozelle import OzelleAdapter
            from app.satellites.fujifilm import FujifilmAdapter
            from app.config import settings

            ozelle_port = getattr(settings, "OZELLE_PORT", 6000)
            fujifilm_host = getattr(settings, "FUJIFILM_HOST", "0.0.0.0")
            fujifilm_port = getattr(settings, "FUJIFILM_PORT", 6001)
            mllp_state.adapters = [
                OzelleAdapter(port=ozelle_port),
                FujifilmAdapter(host=fujifilm_host, port=fujifilm_port),
            ]

        for adapter in mllp_state.adapters:
            if not adapter.is_running():
                logfire.info(f"Iniciando: {adapter.get_source_name()}")
                await adapter.start()

        mllp_state.running = True
        logfire.info("Adaptadores MLLP iniciados correctamente.")
        return templates.TemplateResponse(
            "mllp_status_button.html",
            {"request": request, "mllp_running": mllp_state.running}
        )
    except Exception as e:
        logfire.error(f"Error al iniciar adaptadores MLLP: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al conectar máquinas: {str(e)}",
        )


@router.post("/stop", status_code=status.HTTP_200_OK)
async def stop_mllp_adapters(request: Request):
    if not mllp_state.running:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Las máquinas no están conectadas.",
        )

    logfire.info("Deteniendo adaptadores MLLP desde UI...")
    try:
        for adapter in mllp_state.adapters:
            if adapter.is_running():
                logfire.info(f"Deteniendo: {adapter.get_source_name()}")
                await adapter.stop()

        mllp_state.running = False
        logfire.info("Adaptadores MLLP detenidos correctamente.")
        return templates.TemplateResponse(
            "mllp_status_button.html",
            {"request": request, "mllp_running": mllp_state.running}
        )
    except Exception as e:
        logfire.error(f"Error al detener adaptadores MLLP: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al desconectar máquinas: {str(e)}",
        )


@router.get("/status", status_code=status.HTTP_200_OK)
async def get_mllp_status():
    return {"running": mllp_state.running}


@router.get("/button", response_class=HTMLResponse)
async def get_mllp_button(request: Request):
    return templates.TemplateResponse(
        "mllp_status_button.html",
        {"request": request, "mllp_running": mllp_state.running},
    )
