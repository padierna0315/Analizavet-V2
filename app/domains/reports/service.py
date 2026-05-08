import os
import sys
import subprocess
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
import logfire
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.taller.service import TallerService
from datetime import datetime
from app.config import settings

_MESES_ES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
    5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
    9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
}

def _format_date_es(date_value) -> str:
    """Convierte fecha a formato largo en español: '3 de mayo de 2026'"""
    from datetime import datetime
    if date_value is None:
        return "N/D"
    if isinstance(date_value, str):
        try:
            date_value = datetime.fromisoformat(date_value.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return date_value
    try:
        return f"{date_value.day} de {_MESES_ES[date_value.month]} de {date_value.year}"
    except (AttributeError, KeyError):
        return str(date_value)


# Directorio raíz del proyecto (donde está app/)
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


class ReportService:
    def __init__(self):
        self._taller = TallerService()

        # Setup Jinja2 explicitly for WeasyPrint
        template_dir = Path("app/templates")
        self._jinja_env = Environment(loader=FileSystemLoader(template_dir))

    async def generate_pdf(self, test_result_id: int, session: AsyncSession) -> bytes | None:
        """Fetch data, render HTML, and convert to PDF bytes."""

        # 1. Fetch full data
        data = await self._taller.get_test_result_full(test_result_id, session)
        if not data:
            return None

        # TODO: Integrar imágenes al PDF cuando Santiago defina qué imágenes incluir y cómo.
        # Por ahora se generan sin imágenes para mantener velocidad de generación.
        # Las imágenes siguen extrayéndose y guardándose en disco correctamente.
        images = []  # Sin imágenes en PDF hasta nueva decisión


        # 3. Add absolute paths to images for WeasyPrint to find them
        current_dir = Path.cwd().absolute()
        for img in data["images"]:
            absolute_path = (current_dir / img["file_path"]).as_uri()
            img["absolute_path"] = absolute_path

        # 3. Resolve theme path and read CSS content
        theme_name = getattr(settings, "PDF_THEME", "huellas_lab")
        theme_filepath = current_dir / "app" / "static" / "css" / "themes" / f"{theme_name}.css"
        
        try:
            with open(theme_filepath, 'r') as f:
                theme_css_content = f.read()
        except FileNotFoundError:
            logfire.error(f"Archivo CSS de tema no encontrado: {theme_filepath}")
            theme_css_content = "" # Fallback to empty CSS

        # 4. Render HTML
        template = self._jinja_env.get_template("report/report.html")
        rendered_html = template.render(
            patient=data["patient"],
            test_result=data["test_result"],
            lab_values=data["lab_values"],
            summary=data["summary"],
            images=images,
            theme_css=theme_css_content,
            now=datetime.now(), # Add current datetime for footer
            fecha_es=_format_date_es(data["test_result"].get("received_at")),
        )

        # 5. WeasyPrint en subprocess separado — evita conflicto con uvicorn --reload
        try:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(_PROJECT_ROOT)
            result = subprocess.run(
                [sys.executable, "-m", "app.domains.reports.pdf_worker"],
                input=rendered_html.encode("utf-8"),
                capture_output=True,
                timeout=60,
                cwd=str(_PROJECT_ROOT),
                env=env,
            )
            if result.returncode != 0:
                error = result.stderr.decode("utf-8", errors="ignore")
                logfire.error(f"PDF worker falló: {error}")
                raise RuntimeError(f"Error en PDF worker: {error[:200]}")
            return result.stdout
        except subprocess.TimeoutExpired:
            raise RuntimeError("Timeout generando PDF (>60s)")
        except Exception as e:
            logfire.error(f"Error generando PDF: {e}")
            raise RuntimeError(f"No se pudo generar el PDF: {e}")

    def generate_pdf_sync(self, data: dict) -> bytes | None:
        """
        Versión síncrona pura — recibe datos ya cargados, no necesita DB.
        Diseñada para ejecutarse en un ThreadPoolExecutor desde el endpoint async.
        """
        # TODO: Integrar imágenes al PDF cuando Santiago defina qué imágenes incluir y cómo.
        # Por ahora se generan sin imágenes para mantener velocidad de generación.
        # Las imágenes siguen extrayéndose y guardándose en disco correctamente.
        images = []  # Sin imágenes en PDF hasta nueva decisión

        theme_name = getattr(settings, "PDF_THEME", "huellas_lab")
        current_dir = Path.cwd().absolute()
        theme_filepath = current_dir / "app" / "static" / "css" / "themes" / f"{theme_name}.css"
        try:
            theme_css_content = theme_filepath.read_text()
        except FileNotFoundError:
            theme_css_content = ""

        template = self._jinja_env.get_template("report/report.html")
        rendered_html = template.render(
            patient=data["patient"],
            test_result=data["test_result"],
            lab_values=data["lab_values"],
            summary=data.get("summary", {}),
            images=images,
            theme_css=theme_css_content,
            now=datetime.now(),
            fecha_es=_format_date_es(data["test_result"].get("received_at")),
        )

        from weasyprint import HTML
        return HTML(string=rendered_html).write_pdf()