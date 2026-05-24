"""Approval tests for patients and provenance router refactoring (PR #1, T1.4).

Verify that the shared template engine can render all templates
used by patients and provenance routers, producing identical output
to the standalone jinja2.Environment instances.
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock


class TestPatientsTemplatesShared:
    """Approval: shared template engine renders patients templates correctly."""

    @pytest.fixture
    def shared_env(self):
        """The shared Jinja2Templates environment."""
        from app.template_engine import templates
        return templates.env

    @pytest.fixture
    def standalone_env(self):
        """A standalone jinja2.Environment like the one in patients/router.py."""
        import jinja2
        return jinja2.Environment(
            loader=jinja2.FileSystemLoader("app/templates"),
            autoescape=jinja2.select_autoescape(),
        )

    def test_detail_template_renders_with_shared_env(self, shared_env):
        """patients/detail.html renders correctly with shared env."""
        template = shared_env.get_template("patients/detail.html")
        now = datetime.now(timezone.utc)

        mock_patient = MagicMock()
        mock_patient.id = 1
        mock_patient.name = "Firulais"
        mock_patient.species = "Canino"
        mock_patient.sex = "Macho"
        mock_patient.owner_name = "Juan Pérez"
        mock_patient.age_display = "3 años"
        mock_patient.created_at = now

        html = template.render(
            request={"url": {"path": "/patients/1"}},
            patient=mock_patient,
            test_results=[],
        )

        assert "Firulais" in html
        assert "Canino" in html
        assert "Juan Pérez" in html
        assert "3 años" in html

    def test_list_fragment_renders_with_shared_env(self, shared_env):
        """patients/list_fragment.html renders correctly with shared env."""
        template = shared_env.get_template("patients/list_fragment.html")
        now = datetime.now(timezone.utc)

        mock_p1 = MagicMock()
        mock_p1.id = 1
        mock_p1.name = "Firulais"
        mock_p1.species = "Canino"
        mock_p1.sex = "Macho"
        mock_p1.owner_name = "Owner1"
        mock_p1.updated_at = now

        mock_p2 = MagicMock()
        mock_p2.id = 2
        mock_p2.name = "Mishi"
        mock_p2.species = "Felino"
        mock_p2.sex = "Hembra"
        mock_p2.owner_name = "Owner2"
        mock_p2.updated_at = now

        html = template.render(
            request={"url": {"path": "/patients"}},
            patients=[mock_p1, mock_p2],
            search="",
            page=1,
            next_page=2,
        )

        assert "Firulais" in html
        assert "Mishi" in html
        assert 'hx-get="/patients?page=2' in html

    def test_list_fragment_empty_renders_with_shared_env(self, shared_env):
        """Empty list shows 'no results' message."""
        template = shared_env.get_template("patients/list_fragment.html")
        html = template.render(
            request={"url": {"path": "/patients"}},
            patients=[],
            search="xyz",
            page=1,
            next_page=None,
        )

        assert "No se encontraron pacientes" in html

    def test_index_template_renders_with_shared_env(self, shared_env):
        """patients/index.html (full page) renders with shared env."""
        template = shared_env.get_template("patients/index.html")
        now = datetime.now(timezone.utc)

        html = template.render(
            request={"url": {"path": "/patients"}},
            patients=[],
            search="",
            page=1,
            next_page=None,
        )

        assert "Directorio de Pacientes" in html
        assert "htmx.org" in html

    def test_shared_env_produces_same_output_as_standalone(self, shared_env, standalone_env):
        """Both environments produce identical output for the same template data."""
        template_name = "patients/list_fragment.html"
        now = datetime.now(timezone.utc)

        mock_p = MagicMock()
        mock_p.id = 1
        mock_p.name = "Test"
        mock_p.species = "Test"
        mock_p.sex = "Test"
        mock_p.owner_name = "Test"
        mock_p.updated_at = now

        context = {
            "request": {"url": {"path": "/patients"}},
            "patients": [mock_p],
            "search": "",
            "page": 1,
            "next_page": None,
        }

        shared_html = shared_env.get_template(template_name).render(**context)
        standalone_html = standalone_env.get_template(template_name).render(**context)

        assert shared_html == standalone_html


class TestProvenanceTemplatesShared:
    """Approval: shared template engine renders provenance templates correctly."""

    @pytest.fixture
    def shared_env(self):
        from app.template_engine import templates
        return templates.env

    @pytest.fixture
    def standalone_env(self):
        import jinja2
        return jinja2.Environment(
            loader=jinja2.FileSystemLoader("app/templates"),
            autoescape=jinja2.select_autoescape(),
        )

    def test_raw_data_view_renders_empty_with_shared_env(self, shared_env):
        """provenance/raw_data_view.html renders empty state correctly."""
        template = shared_env.get_template("provenance/raw_data_view.html")
        html = template.render(
            request={"url": {"path": "/patients/1/raw-data"}},
            patient_id=1,
            logs=[],
        )

        assert "raw-data-container" in html
        assert "Sin datos crudos" in html

    def test_raw_data_view_renders_log_with_shared_env(self, shared_env):
        """provenance/raw_data_view.html renders data correctly."""
        template = shared_env.get_template("provenance/raw_data_view.html")
        now = datetime.now(timezone.utc)

        logs = [
            {
                "id": 1,
                "source": "appsheet",
                "raw_data": '{"patients": [{"name": "Firulais"}]}',
                "received_at": now.isoformat(),
                "captured_at": now.isoformat(),
                "processed_at": None,
                "session_code": "A1",
                "status": "linked",
            }
        ]

        html = template.render(
            request={"url": {"path": "/patients/1/raw-data"}},
            patient_id=1,
            logs=logs,
        )

        assert "raw-data-container" in html
        assert "AppSheet" in html
        assert "Firulais" in html
        assert "linked" in html

    def test_shared_env_produces_same_output_as_standalone(self, shared_env, standalone_env):
        """Both environments produce identical output for provenance views."""
        template_name = "provenance/raw_data_view.html"
        now = datetime.now(timezone.utc)

        logs = [
            {
                "id": 1,
                "source": "ozelle",
                "raw_data": "MSH|^~\\&|OZELLE|...",
                "received_at": now.isoformat(),
                "captured_at": now.isoformat(),
                "processed_at": now.isoformat(),
                "session_code": "A1",
                "status": "linked",
            }
        ]

        context = {
            "request": {"url": {"path": "/patients/1/raw-data"}},
            "patient_id": 1,
            "logs": logs,
        }

        shared_html = shared_env.get_template(template_name).render(**context)
        standalone_html = standalone_env.get_template(template_name).render(**context)

        assert shared_html == standalone_html
