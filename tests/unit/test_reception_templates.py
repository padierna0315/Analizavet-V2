"""Tests for reception partial templates (PR #2, T2.1).

RED phase: these templates don't exist yet, so tests will fail with
TemplateNotFound until the template files are created.
"""

import pytest
from jinja2 import Environment, FileSystemLoader, TemplateNotFound


@pytest.fixture
def env():
    """Shared Jinja2 environment (matches template_engine)."""
    return Environment(
        loader=FileSystemLoader("app/templates"),
        autoescape=True,
    )


# ══════════════════════════════════════════════════════════════════════════
# T2.1a: reception/partials/sync_message.html
# ══════════════════════════════════════════════════════════════════════════


class TestSyncMessageTemplate:
    """reception/partials/sync_message.html — sync/archive/restore messages."""

    def test_template_exists(self, env):
        """Template file must exist and load without error."""
        template = env.get_template("reception/partials/sync_message.html")
        assert template is not None

    def test_renders_success_message_with_type_success(self, env):
        """Success type renders div with sync-success class and message."""
        try:
            template = env.get_template("reception/partials/sync_message.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(
            message="✅ 5 paciente(s) sincronizado(s)",
            type="success",
        )

        assert "sync-success" in html
        assert "✅ 5 paciente(s) sincronizado(s)" in html

    def test_renders_error_message_with_type_error(self, env):
        """Error type renders div with sync-error class and message."""
        try:
            template = env.get_template("reception/partials/sync_message.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(
            message="❌ Error: Connection timeout",
            type="error",
        )

        assert "sync-error" in html
        assert "❌ Error: Connection timeout" in html

    def test_message_is_autoescaped(self, env):
        """User-generated message content must be HTML-escaped."""
        try:
            template = env.get_template("reception/partials/sync_message.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(
            message='<script>alert("xss")</script>',
            type="success",
        )

        assert "&lt;script&gt;" in html
        assert "<script>" not in html


# ══════════════════════════════════════════════════════════════════════════
# T2.1b: reception/partials/upload_status.html
# ══════════════════════════════════════════════════════════════════════════


class TestUploadStatusTemplate:
    """reception/partials/upload_status.html — 4 upload status variants."""

    def test_template_exists(self, env):
        """Template file must exist and load without error."""
        template = env.get_template("reception/partials/upload_status.html")
        assert template is not None

    def test_renders_processing_status(self, env):
        """Processing status: polling div with hx-get, hx-trigger every 2s."""
        try:
            template = env.get_template("reception/partials/upload_status.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(
            status="processing",
            upload_id="abc-123",
        )

        assert 'id="upload-status"' in html
        assert 'hx-get="/reception/upload/abc-123/status"' in html
        assert 'hx-trigger="every 2s"' in html
        assert 'hx-swap="outerHTML"' in html
        assert "Procesando archivo" in html

    def test_renders_complete_status(self, env):
        """Complete status: success div with patient count."""
        try:
            template = env.get_template("reception/partials/upload_status.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(
            status="complete",
            count="3",
        )

        assert "upload-success" in html
        assert 'id="upload-status"' in html
        assert "✅ 3 paciente(s) cargado(s)" in html

    def test_renders_error_status(self, env):
        """Error status: error div with error message."""
        try:
            template = env.get_template("reception/partials/upload_status.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(
            status="error",
            error="File format not supported",
        )

        assert "upload-error" in html
        assert 'id="upload-status"' in html
        assert "❌ Error: File format not supported" in html

    def test_renders_not_found_status(self, env):
        """Not-found (None/else) status: error div with expired message."""
        try:
            template = env.get_template("reception/partials/upload_status.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(
            status="not_found",
        )

        assert "upload-error" in html
        assert 'id="upload-status"' in html
        assert "Estado no encontrado" in html

    def test_count_is_autoescaped_in_complete(self, env):
        """Count value must be autoescaped (though normally numeric)."""
        try:
            template = env.get_template("reception/partials/upload_status.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(
            status="complete",
            count='<b>5</b>',
        )

        assert "&lt;b&gt;" in html
        assert "<b>" not in html

    def test_error_message_is_autoescaped(self, env):
        """Error message must be autoescaped."""
        try:
            template = env.get_template("reception/partials/upload_status.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(
            status="error",
            error='<img src=x onerror=alert(1)>',
        )

        assert "&lt;img" in html
        assert "<img" not in html


# ══════════════════════════════════════════════════════════════════════════
# T2.1c: reception/partials/archived_grid.html
# ══════════════════════════════════════════════════════════════════════════


class TestArchivedGridTemplate:
    """reception/partials/archived_grid.html — archived patients grid."""

    def test_template_exists(self, env):
        """Template file must exist and load without error."""
        template = env.get_template("reception/partials/archived_grid.html")
        assert template is not None

    def test_renders_empty_message_when_empty(self, env):
        """Empty flag produces centered 'no results' message."""
        try:
            template = env.get_template("reception/partials/archived_grid.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(
            patients=[],
            empty=True,
        )

        assert "Sin resultados archivados" in html
        assert "patient-card" not in html
        assert "archived-grid" not in html

    def test_renders_grid_with_patients(self, env):
        """Non-empty list renders archived-grid with patient cards."""
        try:
            template = env.get_template("reception/partials/archived_grid.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        patients = [
            {
                "id": 1,
                "name": "Firulais",
                "species": "Canino",
                "session_code": None,
                "owner_name": "Juan",
            },
            {
                "id": 2,
                "name": "Mishi",
                "species": "Felino",
                "session_code": "A1",
                "owner_name": None,
            },
        ]

        html = template.render(
            patients=patients,
            empty=False,
        )

        assert "archived-grid" in html
        # Count class="patient-card" (each card has it once)
        assert html.count('class="patient-card"') == 2
        assert "Firulais" in html
        assert "Mishi" in html
        assert "Canino" in html
        assert "Felino" in html

    def test_preserves_hx_on_after_request_attribute(self, env):
        """Restore button must have hx-on::after-request exactly as original."""
        try:
            template = env.get_template("reception/partials/archived_grid.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        patients = [
            {"id": 1, "name": "Test", "species": "Test",
             "session_code": None, "owner_name": None},
        ]

        html = template.render(patients=patients, empty=False)

        assert 'hx-on::after-request' in html
        assert "document.getElementById('patient-card-1').remove()" in html
        assert "location.reload()" in html

    def test_preserves_htmx_attrs_on_restore_button(self, env):
        """Restore button preserves hx-post, hx-target, hx-swap."""
        try:
            template = env.get_template("reception/partials/archived_grid.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        patients = [
            {"id": 42, "name": "Test", "species": "Test",
             "session_code": None, "owner_name": None},
        ]

        html = template.render(patients=patients, empty=False)

        assert 'hx-post="/reception/patient/42/restore"' in html
        assert 'hx-target="#sync-status"' in html
        assert 'hx-swap="innerHTML"' in html

    def test_session_code_label_renders_when_present(self, env):
        """Session code prefix renders when session_code is provided."""
        try:
            template = env.get_template("reception/partials/archived_grid.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        patients = [
            {"id": 1, "name": "Firulais", "species": "Canino",
             "session_code": "A1", "owner_name": None},
        ]

        html = template.render(patients=patients, empty=False)

        assert "A1 - Firulais" in html

    def test_patient_name_is_autoescaped(self, env):
        """Patient name must be autoescaped to prevent XSS."""
        try:
            template = env.get_template("reception/partials/archived_grid.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        patients = [
            {"id": 1, "name": "<img src=x>", "species": "Test",
             "session_code": None, "owner_name": None},
        ]

        html = template.render(patients=patients, empty=False)

        assert "&lt;img src=x&gt;" in html
        assert "<img" not in html
