"""Tests for main.py partial templates (PR #1, T1.2).

These are approval/snapshot tests that capture the expected output
of the new templates so they match the current inline HTML exactly.
"""
import pytest
from unittest.mock import MagicMock


class TestAdapterCardsTemplate:
    """T1.2a: main/partials/adapter_cards.html renders adapter status cards."""

    @pytest.fixture
    def env(self):
        """Shared Jinja2 environment (matches template_engine)."""
        from jinja2 import Environment, FileSystemLoader
        return Environment(
            loader=FileSystemLoader("app/templates"),
            autoescape=True,
        )

    def test_renders_single_running_adapter(self, env):
        """A single running adapter should produce a card with 'active' class."""
        template = env.get_template("main/partials/adapter_cards.html")
        html = template.render(
            request={"url": {"path": "/api/adapters/status"}},
            adapters=[
                {"name": "Ozelle", "is_running": True},
            ],
        )

        assert "adapter-card" in html
        assert "Ozelle" in html
        assert "active" in html
        assert "Conectado" in html

    def test_renders_single_stopped_adapter(self, env):
        """A stopped adapter should produce a card with 'inactive' class."""
        template = env.get_template("main/partials/adapter_cards.html")
        html = template.render(
            request={"url": {"path": "/api/adapters/status"}},
            adapters=[
                {"name": "Fujifilm", "is_running": False},
            ],
        )

        assert "adapter-card" in html
        assert "Fujifilm" in html
        assert "inactive" in html
        assert "Desconectado" in html

    def test_renders_multiple_adapters(self, env):
        """Multiple adapters should produce cards for each."""
        template = env.get_template("main/partials/adapter_cards.html")
        html = template.render(
            request={"url": {"path": "/api/adapters/status"}},
            adapters=[
                {"name": "Ozelle", "is_running": True},
                {"name": "Fujifilm", "is_running": False},
            ],
        )

        assert html.count("adapter-card") == 2
        assert "Ozelle" in html
        assert "Fujifilm" in html

    def test_renders_empty_when_no_adapters(self, env):
        """Empty adapters list should produce empty HTML output."""
        template = env.get_template("main/partials/adapter_cards.html")
        html = template.render(
            request={"url": {"path": "/api/adapters/status"}},
            adapters=[],
        )

        # Should be empty string or whitespace-only
        assert html.strip() == ""

    def test_adapter_name_is_autoescaped(self, env):
        """Adapter name containing HTML chars should be escaped."""
        template = env.get_template("main/partials/adapter_cards.html")
        html = template.render(
            request={"url": {"path": "/api/adapters/status"}},
            adapters=[
                {"name": "<script>alert(1)</script>", "is_running": True},
            ],
        )

        # HTML special chars should be escaped
        assert "&lt;script&gt;" in html
        assert "<script>" not in html


class TestErrorAlertTemplate:
    """T1.2b: main/partials/error_alert.html renders the global error alert."""

    @pytest.fixture
    def env(self):
        from jinja2 import Environment, FileSystemLoader
        return Environment(
            loader=FileSystemLoader("app/templates"),
            autoescape=True,
        )

    def test_renders_error_with_detail(self, env):
        """Template should render error alert with the detail string."""
        template = env.get_template("main/partials/error_alert.html")
        html = template.render(
            request={"url": {"path": "/test"}},
            detail="Test error message",
        )

        assert "Error del Sistema" in html
        assert "Test error message" in html
        assert "Ha ocurrido un problema inesperado" in html

    def test_detail_is_autoescaped(self, env):
        """Error detail containing HTML should be autoescaped."""
        template = env.get_template("main/partials/error_alert.html")
        html = template.render(
            request={"url": {"path": "/test"}},
            detail="<img src=x onerror=alert(1)>",
        )

        assert "&lt;img" in html
        assert "<img" not in html or "&lt;img" in html

    def test_renders_with_safe_inline_styles(self, env):
        """Inline styles should be preserved as-is in the template."""
        template = env.get_template("main/partials/error_alert.html")
        html = template.render(
            request={"url": {"path": "/test"}},
            detail="Some error",
        )

        assert "background-color: #fef2f2" in html
        assert "border-left: 4px solid #dc2626" in html
