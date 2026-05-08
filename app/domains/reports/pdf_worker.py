"""
PDF Worker — ejecuta WeasyPrint en un subprocess separado.
Esto evita el conflicto entre WeasyPrint (Cairo/Pango/GObject) y uvicorn --reload.

Uso: python -m app.core.reports.pdf_worker <html_file> <output_file>
"""
import sys
from pathlib import Path


def generate(html_content: str) -> bytes:
    """Genera PDF a partir de HTML. Llamar desde subprocess."""
    from weasyprint import HTML
    return HTML(string=html_content).write_pdf()


if __name__ == "__main__":
    # Lee HTML desde stdin, escribe PDF a stdout
    html = sys.stdin.buffer.read().decode("utf-8")
    pdf = generate(html)
    sys.stdout.buffer.write(pdf)
