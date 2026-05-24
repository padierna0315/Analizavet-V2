"""Approval tests for main.py refactoring (PR #1, T1.3).

These tests capture the CURRENT behavior of main.py endpoints BEFORE
the inline-HTML-to-template migration. After the refactoring, these
SAME tests must still pass, proving byte-identical output.
"""
import pytest
from unittest.mock import MagicMock
from httpx import AsyncClient, ASGITransport


class TestAdaptersStatusApproval:
    """Approval: GET /api/adapters/status — capture current inline HTML output."""

    @pytest.fixture
    def app_with_adapters(self):
        """Load the real app with mock adapters set up."""
        import app.mllp_state as mllp_state

        # Import must happen here to pick up the already-configured app
        from app.main import app

        # Mock the adapters list with realistic data
        mock_ozelle = MagicMock()
        mock_ozelle.get_source_name.return_value = "Ozelle"
        mock_ozelle.is_running.return_value = True

        mock_fuji = MagicMock()
        mock_fuji.get_source_name.return_value = "Fujifilm"
        mock_fuji.is_running.return_value = False

        # Save original and replace
        original = list(mllp_state.adapters) if hasattr(mllp_state, 'adapters') else []
        mllp_state.adapters = [mock_ozelle, mock_fuji]

        yield app

        # Restore
        mllp_state.adapters = original

    @pytest.mark.asyncio
    async def test_adapters_status_returns_html_cards(self, app_with_adapters):
        """GET /api/adapters/status returns HTML with adapter cards."""
        async with AsyncClient(
            transport=ASGITransport(app=app_with_adapters),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/adapters/status")

        assert response.status_code == 200
        html = response.text
        # Both adapters should appear
        assert "Ozelle" in html
        assert "Fujifilm" in html
        # Status classes should match
        assert "active" in html
        assert "inactive" in html
        # Status titles
        assert "Conectado" in html
        assert "Desconectado" in html
        # Card structure
        assert "adapter-card" in html
        assert "adapter-icon" in html
        assert "adapter-name" in html
        assert "adapter-status" in html

    @pytest.mark.asyncio
    async def test_adapters_status_empty_list(self):
        """With no adapters, returns empty HTML without error."""
        import app.mllp_state as mllp_state
        from app.main import app

        original = list(mllp_state.adapters)
        mllp_state.adapters = []

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                response = await client.get("/api/adapters/status")

            assert response.status_code == 200
            assert "adapter-card" not in response.text
        finally:
            mllp_state.adapters = original


class TestExceptionHandlerApproval:
    """Approval: global_exception_handler — capture current inline HTML output.

    Note: FastAPI's TestClient (raise_server_exceptions=False) routes
    exceptions through custom handlers. ASGITransport + httpx catches
    them at the ServerErrorMiddleware level instead.
    """

    @pytest.fixture
    def client_with_error_route(self):
        """Create a TestClient that hits the real app's exception handler."""
        from app.main import app
        from starlette.testclient import TestClient

        # Register a test route that raises
        @app.get("/test-global-error")
        async def test_error():
            raise ValueError("Test approval error")

        with TestClient(app, raise_server_exceptions=False) as client:
            yield client

    def test_htmx_request_returns_html_error(self, client_with_error_route):
        """When accept: text/html header is present, returns HTML error page."""
        response = client_with_error_route.get(
            "/test-global-error",
            headers={"accept": "text/html"},
        )

        assert response.status_code == 500
        html = response.text
        assert "Error del Sistema" in html
        assert "Test approval error" in html
        assert "Ha ocurrido un problema inesperado" in html
        assert "Detalle técnico" in html

    def test_htmx_request_header_returns_html_error(self, client_with_error_route):
        """When hx-request header is present, also returns HTML error."""
        response = client_with_error_route.get(
            "/test-global-error",
            headers={"hx-request": "true"},
        )

        assert response.status_code == 500
        html = response.text
        assert "Error del Sistema" in html

    def test_api_request_returns_json_error(self, client_with_error_route):
        """When accept is application/json (not HTML), returns JSON."""
        response = client_with_error_route.get(
            "/test-global-error",
            headers={"accept": "application/json"},
        )

        assert response.status_code == 500
        data = response.json()
        assert "detail" in data
        assert "Error interno" in data["detail"]
