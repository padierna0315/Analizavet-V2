"""Tests for shared template engine module (PR #1, T1.1)."""

import pytest
from fastapi.templating import Jinja2Templates
from markupsafe import Markup


class TestTemplateEngineSingleton:
    """T1.1: app.template_engine provides a shared Jinja2Templates singleton
    with the format_ref_range filter registered."""

    def test_templates_is_jinja2templates_instance(self):
        """The module-level `templates` must be a Jinja2Templates instance."""
        from app.template_engine import templates
        from starlette.templating import Jinja2Templates as StarletteJinja2Templates

        assert isinstance(templates, StarletteJinja2Templates)
        # Verify the loader knows about app/templates
        assert templates.env is not None
        loader = templates.env.loader
        assert hasattr(loader, "searchpath")
        assert any("templates" in p for p in loader.searchpath)

    def test_format_ref_range_filter_is_registered(self):
        """The format_ref_range filter must be registered in the shared
        Jinja2Templates environment."""
        from app.template_engine import templates

        # Jinja2Templates stores filters in its .env.filters dict
        env = getattr(templates, "env", None)
        assert env is not None, "Jinja2Templates must have an .env attribute"
        assert "format_ref_range" in env.filters

    def test_format_ref_range_filter_works_correctly(self):
        """The registered filter must produce valid output for a normal range."""
        from app.template_engine import templates

        env = templates.env
        filter_fn = env.filters["format_ref_range"]

        result = filter_fn("10 - 200 mg/dL")
        assert isinstance(result, Markup)
        assert "10" in str(result)
        assert "200" in str(result)
        assert "mg/dL" in str(result)

    def test_format_ref_range_filter_handles_nd(self):
        """N/D values pass through unchanged."""
        from app.template_engine import templates

        env = templates.env
        filter_fn = env.filters["format_ref_range"]

        result = filter_fn("N/D")
        assert str(result) == "N/D"

    def test_template_env_has_autoescape_enabled(self):
        """The shared template engine must have autoescape enabled
        (select_autoescape is a callable that returns True for HTML files)."""
        from app.template_engine import templates

        env = templates.env
        # Jinja2 autoescape can be True, False, or a callable.
        # FastAPI's Jinja2Templates sets it to jinja2.select_autoescape()
        # which is a callable — call it with an html extension to verify.
        import jinja2
        autoescape = env.autoescape
        if callable(autoescape):
            assert autoescape("file.html") is True
        else:
            assert autoescape is True


class TestTemplateEngineRendering:
    """T1.1: Verify the shared templates instance can actually render templates."""

    def test_can_render_simple_template(self):
        """A simple inline template should render correctly through the shared instance."""
        from app.template_engine import templates
        from jinja2 import Environment

        # Create a minimal template in the env and render it
        env = templates.env
        template = env.from_string("Hello, {{ name }}!")
        result = template.render(name="World")
        assert result == "Hello, World!"

    def test_can_render_with_request_context(self):
        """TemplateResponse should work with the shared instance and request context."""
        from app.template_engine import templates
        from starlette.testclient import TestClient
        from fastapi import FastAPI, Request

        app = FastAPI()

        # Use a minimal Jinja2 template string (from_string) via the shared env
        simple_env = templates.env

        @app.get("/test-template")
        async def test_endpoint(request: Request):
            tmpl = simple_env.from_string("Patient {{ patient_id }} — {{ request.url.path }}")
            html = tmpl.render(request=request, patient_id=42)
            from starlette.responses import HTMLResponse
            return HTMLResponse(content=html)

        client = TestClient(app)
        response = client.get("/test-template")
        assert response.status_code == 200
        assert "42" in response.text
        assert "/test-template" in response.text
