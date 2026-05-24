"""
Shared Jinja2Templates instance used by all routers.

This module provides a single, pre-configured Jinja2Templates singleton
that all domains import instead of creating standalone jinja2.Environment
or Jinja2Templates instances. Filters are registered once here.
"""
from fastapi.templating import Jinja2Templates

# ── Shared template engine ───────────────────────────────────────────────────
# Every router imports this instance. Autoescape is enabled by default
# (jinja2.select_autoescape(['html', 'htm', 'xml']) by FastAPI).
templates = Jinja2Templates(directory="app/templates")

# ── Register shared filters ──────────────────────────────────────────────────
# Filters that multiple templates need are registered here so every
# consumer of `templates` gets them without extra setup.
from app.domains.reports.filters import format_ref_range

templates.env.filters["format_ref_range"] = format_ref_range
