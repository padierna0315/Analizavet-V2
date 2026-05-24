"""Tests for notification toast template (PR #3, T3.2).

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
# T3.2a: notifications/partials/toast.html
# ══════════════════════════════════════════════════════════════════════════


class TestToastTemplate:
    """notifications/partials/toast.html — notification toast fragment."""

    def test_template_exists(self, env):
        """Template file must exist and load without error."""
        template = env.get_template("notifications/partials/toast.html")
        assert template is not None

    def test_renders_success_toast(self, env):
        """Success notification type renders with green classes."""
        try:
            template = env.get_template("notifications/partials/toast.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(
            message="✅ Operación completada",
            notification_type="success",
            auto_dismiss=True,
            extra_classes="",
        )

        assert "notification-container" in html
        assert 'hx-swap-oob="true"' in html
        assert "notification-toast" in html
        assert "success" in html
        assert "auto-dismiss" in html
        assert "✅ Operación completada" in html

    def test_renders_error_toast(self, env):
        """Error notification type renders with error class."""
        try:
            template = env.get_template("notifications/partials/toast.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(
            message="✕ Error: Conexión fallida",
            notification_type="error",
            auto_dismiss=True,
            extra_classes="",
        )

        assert "notification-toast" in html
        assert "error" in html
        assert "auto-dismiss" in html
        assert "✕ Error: Conexión fallida" in html

    def test_renders_processing_toast(self, env):
        """Processing notification type renders with processing class."""
        try:
            template = env.get_template("notifications/partials/toast.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(
            message="⟳ Procesando datos...",
            notification_type="processing",
            auto_dismiss=False,
            extra_classes="",
        )

        assert "notification-toast" in html
        assert "processing" in html
        assert "auto-dismiss" not in html
        assert "⟳ Procesando datos..." in html

    def test_no_auto_dismiss_when_false(self, env):
        """When auto_dismiss is False, the auto-dismiss class must NOT be present."""
        try:
            template = env.get_template("notifications/partials/toast.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(
            message="Procesando...",
            notification_type="processing",
            auto_dismiss=False,
            extra_classes="",
        )

        assert "auto-dismiss" not in html

    def test_preserves_oob_swap_attribute(self, env):
        """Container div MUST have hx-swap-oob='true'."""
        try:
            template = env.get_template("notifications/partials/toast.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(
            message="Test message",
            notification_type="success",
            auto_dismiss=True,
            extra_classes="",
        )

        assert 'hx-swap-oob="true"' in html

    def test_message_is_autoescaped(self, env):
        """Message with HTML special chars must be autoescaped."""
        try:
            template = env.get_template("notifications/partials/toast.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(
            message='<script>alert("xss")</script>',
            notification_type="success",
            auto_dismiss=True,
            extra_classes="",
        )

        assert "&lt;script&gt;" in html
        assert "<script>" not in html

    def test_extra_classes_rendered(self, env):
        """extra_classes string must be appended to notification div."""
        try:
            template = env.get_template("notifications/partials/toast.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(
            message="Mensaje con clase extra",
            notification_type="success",
            auto_dismiss=True,
            extra_classes="top-right",
        )

        assert "top-right" in html

    def test_toast_container_has_correct_id(self, env):
        """The OOB container div must have id='notification-container'."""
        try:
            template = env.get_template("notifications/partials/toast.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(
            message="test",
            notification_type="success",
            auto_dismiss=True,
            extra_classes="",
        )

        assert 'id="notification-container"' in html


# ══════════════════════════════════════════════════════════════════════════
# T3.2b: taller/doctors/partials/doctor_options.html
# ══════════════════════════════════════════════════════════════════════════


class TestDoctorOptionsTemplate:
    """taller/doctors/partials/doctor_options.html — doctor dropdown options."""

    def test_template_exists(self, env):
        """Template file must exist and load without error."""
        template = env.get_template("taller/doctors/partials/doctor_options.html")
        assert template is not None

    def test_renders_default_option_first(self, env):
        """First option must be '-- Seleccionar médico --' with empty value."""
        try:
            template = env.get_template("taller/doctors/partials/doctor_options.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        doctors = [{"id": 1, "name": "Dr. García"}]
        html = template.render(doctors=doctors, selected_name="")

        assert '<option value="">-- Seleccionar médico --</option>' in html

    def test_renders_doctor_options(self, env):
        """All doctor names appear as option elements."""
        try:
            template = env.get_template("taller/doctors/partials/doctor_options.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        doctors = [
            {"id": 1, "name": "Dr. García"},
            {"id": 2, "name": "Dra. Martínez"},
            {"id": 3, "name": "Dr. López"},
        ]
        html = template.render(doctors=doctors, selected_name="")

        assert "Dr. García" in html
        assert "Dra. Martínez" in html
        assert "Dr. López" in html

    def test_preselected_doctor_has_selected_attribute(self, env):
        """The currently selected doctor must have 'selected' attribute."""
        try:
            template = env.get_template("taller/doctors/partials/doctor_options.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        doctors = [
            {"id": 1, "name": "Dr. García"},
            {"id": 2, "name": "Dra. Martínez"},
        ]
        html = template.render(doctors=doctors, selected_name="Dra. Martínez")

        assert '<option value="Dra. Martínez" selected>' in html

    def test_doctor_names_autoescaped(self, env):
        """Doctor names with HTML chars must be autoescaped."""
        try:
            template = env.get_template("taller/doctors/partials/doctor_options.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        doctors = [{"id": 1, "name": 'Dr. <script>evil</script>'}]
        html = template.render(doctors=doctors, selected_name="")

        assert "&lt;script&gt;" in html
        assert "<script>" not in html


# ══════════════════════════════════════════════════════════════════════════
# T3.2c: taller/doctors/partials/add_doctor_form.html
# ══════════════════════════════════════════════════════════════════════════


class TestAddDoctorFormTemplate:
    """taller/doctors/partials/add_doctor_form.html — modal form to add a doctor."""

    def test_template_exists(self, env):
        """Template file must exist and load without error."""
        template = env.get_template("taller/doctors/partials/add_doctor_form.html")
        assert template is not None

    def test_renders_modal_form_structure(self, env):
        """Form must have correct modal id, hx-post, hx-target, hx-swap."""
        try:
            template = env.get_template("taller/doctors/partials/add_doctor_form.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render()

        assert 'id="doctor-modal-content"' in html
        assert "modal-content" in html

    def test_form_posts_to_correct_endpoint(self, env):
        """Form hx-post must target /taller/doctors/."""
        try:
            template = env.get_template("taller/doctors/partials/add_doctor_form.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render()

        assert 'hx-post="/taller/doctors/"' in html

    def test_form_targets_doctor_select(self, env):
        """Form hx-target must be #doctor-select with innerHTML swap."""
        try:
            template = env.get_template("taller/doctors/partials/add_doctor_form.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render()

        assert 'hx-target="#doctor-select"' in html
        assert 'hx-swap="innerHTML"' in html

    def test_has_name_input_field(self, env):
        """Form must have a required name input."""
        try:
            template = env.get_template("taller/doctors/partials/add_doctor_form.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render()

        assert 'name="name"' in html
        assert "required" in html
        assert "Nombre" in html

    def test_has_specialty_input_field(self, env):
        """Form must have an optional specialty input."""
        try:
            template = env.get_template("taller/doctors/partials/add_doctor_form.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render()

        assert 'name="specialty"' in html
        assert "Especialidad" in html

    def test_has_cancel_button_with_close_modal(self, env):
        """Cancel button must use hx-get to /reception/close-modal."""
        try:
            template = env.get_template("taller/doctors/partials/add_doctor_form.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render()

        assert 'hx-get="/reception/close-modal"' in html
        assert "Cancelar" in html
