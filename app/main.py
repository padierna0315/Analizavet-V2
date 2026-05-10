import logfire
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from app.domains.health.router import router as health_router
from app.domains.mllp.router import router as mllp_router
from app.domains.reception.router import router as reception_router
from app.domains.taller.router import router as taller_router
from app.domains.reports.router import router as reports_router
from app.domains.patients.router import router as patients_ui_router
from app.domains.editor.router import router as editor_router
from app.logging_config import setup_logging
from app.config import settings
from app.satellites.ozelle import OzelleAdapter
from app.satellites.fujifilm import FujifilmAdapter
from app.database import create_db_and_tables
import os


# Logfire configuration - local mode only (no internet)
if settings.LOGFIRE_ENABLED:
    logfire.configure(
        send_to_logfire=False,  # Modo local — sin conexión a internet
        service_name="analizavet-v2",
    )
    logfire.instrument_pydantic()  # Captura validaciones de Pydantic


# Estado MLLP — en módulo separado para compartir entre main.py y routers/mllp.py
import app.mllp_state as mllp_state

# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(settings.LOG_LEVEL)
    logfire.info("Iniciando servicios...")

    # Create DB tables if they don't exist
    logfire.info("Verificando base de datos...")
    await create_db_and_tables()

    # Initialize adapters
    # Only start adapters if not in testing environment and MLLP is enabled
    if os.environ.get("TESTING") != "True" and settings.MLLP_ENABLED:
        ozelle_port = getattr(settings, "OZELLE_PORT", 6000)
        fujifilm_host = getattr(settings, "FUJIFILM_HOST", "0.0.0.0")
        fujifilm_port = getattr(settings, "FUJIFILM_PORT", 6001)

        mllp_state.adapters = [
            OzelleAdapter(port=ozelle_port),
            FujifilmAdapter(host=fujifilm_host, port=fujifilm_port),
        ]

        for adapter in mllp_state.adapters:
            logfire.info(f"Iniciando adaptador: {adapter.get_source_name()}")
            await adapter.start()
        mllp_state.running = True
    else:
        logfire.info("MLLP_ENABLED=False. Adaptadores no iniciados — usa el botón en la UI para arrancarlos.")
        mllp_state.adapters = []
        mllp_state.running = False

    yield

    # Shutdown all adapters
    logfire.info("Deteniendo servicios...")
    for adapter in mllp_state.adapters:
        logfire.info(f"Deteniendo adaptador: {adapter.get_source_name()}")
        try:
            await adapter.stop()
        except Exception as e:
            logfire.error(f"Error deteniendo {adapter.get_source_name()}: {e}")

# ── Application Setup ──────────────────────────────────────────────────────────

app = FastAPI(title="Analizavet V2", version="2.0.0", lifespan=lifespan)
if settings.LOGFIRE_ENABLED:
    logfire.instrument_fastapi(app)  # Captura todas las peticiones HTTP

@app.get("/", include_in_schema=False)
async def root_redirect():
    """Redirigir la raíz al Taller Interactivo (Historia Clínica)."""
    return RedirectResponse(url="/taller/", status_code=302)

app.include_router(health_router)
app.include_router(mllp_router)
app.include_router(reception_router)
app.include_router(taller_router)
app.include_router(reports_router)
app.include_router(patients_ui_router)
app.include_router(editor_router)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/images", StaticFiles(directory=settings.IMAGES_DIR), name="images")
templates = Jinja2Templates(directory="app/templates")


@app.get("/api/adapters/status", response_class=HTMLResponse)
async def get_adapters_status():
    """Return HTML status cards for all LIS adapters."""
    from app.mllp_state import adapters
    html_cards = ""
    for adapter in adapters:
        name = adapter.get_source_name()
        is_running = adapter.is_running()
        status_class = "active" if is_running else "inactive"
        status_text = "Conectado" if is_running else "Desconectado"
        html_cards += f'''<div class="adapter-card">
    <span class="adapter-icon">🩸</span>
    <span class="adapter-name">{name}</span>
    <span class="adapter-status {status_class}" title="{status_text}"></span>
</div>'''
    return html_cards


# ── Global Exception Handlers ──────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logfire.error(f"Error global no manejado en {request.url.path}: {exc}")

    # If it's an HTMX request or browser request, return HTML
    if "text/html" in request.headers.get("accept", "") or request.headers.get("hx-request"):
        return HTMLResponse(
            content=f"""
            <div style="background-color: #fef2f2; color: #991b1b; padding: 1rem; border-left: 4px solid #dc2626; margin: 1rem 0;">
                <h3 style="margin-top: 0;">⚠️ Error del Sistema</h3>
                <p>Ha ocurrido un problema inesperado. Por favor, intente nuevamente o contacte al administrador.</p>
                <p style="font-size: 0.8em; color: #b91c1c; margin-bottom: 0;">Detalle técnico: {str(exc)}</p>
            </div>
            """,
            status_code=500
        )

    # Otherwise return JSON (for APIs)
    return JSONResponse(
        status_code=500,
        content={"detail": "Error interno del servidor. Por favor intente más tarde."}
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logfire.warning(f"Error de validación de datos en {request.url.path}: {exc.errors()}")
    return JSONResponse(
        status_code=422,
        content={"detail": "Los datos enviados son incorrectos o están incompletos.", "errores": exc.errors()}
    )
