"""Tests for taller partial templates (PR #3, T3.1).

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
# T3.1a: taller/partials/pending_patients.html
# ══════════════════════════════════════════════════════════════════════════


class TestPendingPatientsTemplate:
    """taller/partials/pending_patients.html — pending patients list."""

    def test_template_exists(self, env):
        """Template file must exist and load without error."""
        template = env.get_template("taller/partials/pending_patients.html")
        assert template is not None

    def test_renders_patient_list_with_data(self, env):
        """Template renders patient items with name, species, owner, test_type."""
        try:
            template = env.get_template("taller/partials/pending_patients.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        patients = [
            {
                "test_id": 1,
                "patient_id": 10,
                "name": "Kitty",
                "species": "Felino",
                "owner_name": "Laura Cepeda",
                "test_type": "Hemograma",
            },
            {
                "test_id": 2,
                "patient_id": 11,
                "name": "Rex",
                "species": "Canino",
                "owner_name": "Juan Pérez",
                "test_type": "Perfil Renal",
            },
        ]

        html = template.render(patients=patients)

        assert "Kitty" in html
        assert "Felino" in html
        assert "Laura Cepeda" in html
        assert "Hemograma" in html
        assert "Rex" in html
        assert "Canino" in html
        assert "Juan Pérez" in html
        assert "Perfil Renal" in html

    def test_renders_empty_message_when_no_patients(self, env):
        """Empty list renders 'No hay pacientes en cola' message."""
        try:
            template = env.get_template("taller/partials/pending_patients.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(patients=[])
        assert "No hay pacientes en cola" in html

    def test_preserves_htmx_attributes_on_items(self, env):
        """Each patient item div must have correct hx-post, hx-target, hx-swap."""
        try:
            template = env.get_template("taller/partials/pending_patients.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        patients = [
            {
                "test_id": 5,
                "patient_id": 20,
                "name": "Luna",
                "species": "Felino",
                "owner_name": "María",
                "test_type": "Citoquímico",
            },
        ]

        html = template.render(patients=patients)

        assert 'hx-post="/taller/load-patient/5"' in html
        assert 'hx-target=".taller-workspace"' in html
        assert 'hx-swap="innerHTML"' in html
        assert "pending-patient-item" in html

    def test_preserves_delete_button_htmx_attributes(self, env):
        """Delete button must have hx-delete, hx-confirm, hx-swap attrs."""
        try:
            template = env.get_template("taller/partials/pending_patients.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        patients = [
            {
                "test_id": 1,
                "patient_id": 99,
                "name": "Max",
                "species": "Canino",
                "owner_name": "Pedro",
                "test_type": "Hemograma",
            },
        ]

        html = template.render(patients=patients)

        assert 'hx-delete="/taller/pending-patient/99"' in html
        assert 'hx-confirm="¿Eliminar de la cola?"' in html
        assert 'hx-swap="outerHTML swap:300ms"' in html

    def test_patient_name_is_autoescaped(self, env):
        """Patient name with HTML special chars must be escaped."""
        try:
            template = env.get_template("taller/partials/pending_patients.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        patients = [
            {
                "test_id": 1,
                "patient_id": 10,
                "name": '<script>alert("xss")</script>',
                "species": "Felino",
                "owner_name": "Laura",
                "test_type": "Hemograma",
            },
        ]

        html = template.render(patients=patients)

        assert "&lt;script&gt;" in html
        assert '<script>alert(' not in html

    def test_owner_name_is_autoescaped(self, env):
        """Owner name with HTML special chars must be escaped (triangulation)."""
        try:
            template = env.get_template("taller/partials/pending_patients.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        patients = [
            {
                "test_id": 1,
                "patient_id": 10,
                "name": "Kitty",
                "species": "Felino",
                "owner_name": 'Luis & María <bad>',
                "test_type": "Hemograma",
            },
        ]

        html = template.render(patients=patients)

        assert "Luis &amp; María &lt;bad&gt;" in html
        assert "<bad>" not in html


# ══════════════════════════════════════════════════════════════════════════
# T3.1b: taller/partials/workspace.html  (the ~120-line big one)
# ══════════════════════════════════════════════════════════════════════════


class TestWorkspaceTemplate:
    """taller/partials/workspace.html — two-column patient workspace."""

    def test_template_exists(self, env):
        """Template file must exist and load without error."""
        template = env.get_template("taller/partials/workspace.html")
        assert template is not None

    @pytest.fixture
    def workspace_context(self):
        """Typical context for workspace template."""
        return {
            "result_id": 42,
            "patient": {
                "name": "Kitty",
                "species": "Felino",
                "sex": "Hembra",
                "age_display": "2 años",
                "owner_name": "Laura Cepeda",
                "breed": "Criollo",
            },
            "test_result": {
                "test_type": "Hemograma",
                "doctor_name": "Dr. García",
            },
            "lab_values": [
                {
                    "parameter_code": "WBC",
                    "parameter_name_es": "Leucocitos",
                    "raw_value": "14.26",
                    "unit": "10*9/L",
                    "reference_range": "5.05-16.76",
                    "flag": "NORMAL",
                },
                {
                    "parameter_code": "HGB",
                    "parameter_name_es": "Hemoglobina",
                    "raw_value": "5.0",
                    "unit": "g/dL",
                    "reference_range": "13.1-20.5",
                    "flag": "BAJO",
                },
            ],
            "doctors": [
                {"id": 1, "name": "Dr. García"},
                {"id": 2, "name": "Dra. Martínez"},
            ],
        }

    def test_renders_patient_form_fields(self, env, workspace_context):
        """Workspace renders patient form with name, species, sex, age, breed, owner."""
        try:
            template = env.get_template("taller/partials/workspace.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(**workspace_context)

        assert "Kitty" in html
        assert "Felino" in html
        assert "Hembra" in html
        assert "2 años" in html
        assert "Laura Cepeda" in html
        assert "Criollo" in html

    def test_renders_lab_values_table(self, env, workspace_context):
        """Workspace renders lab values table with parameter names and values."""
        try:
            template = env.get_template("taller/partials/workspace.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(**workspace_context)

        assert "Leucocitos" in html
        assert "14.26" in html
        assert "5.05-16.76" in html
        assert "Hemoglobina" in html
        assert "5.0" in html

    def test_renders_flag_css_classes(self, env, workspace_context):
        """Lab rows render with flag-specific CSS classes (flag-alto, flag-bajo, flag-normal)."""
        try:
            template = env.get_template("taller/partials/workspace.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(**workspace_context)

        assert "flag-normal" in html
        assert "flag-bajo" in html

    def test_renders_doctor_dropdown(self, env, workspace_context):
        """Doctor dropdown with options, current doctor pre-selected."""
        try:
            template = env.get_template("taller/partials/workspace.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(**workspace_context)

        assert "Dr. García" in html
        assert "Dra. Martínez" in html
        assert "doctor-select" in html

    def test_preserves_form_htmx_attributes(self, env, workspace_context):
        """Form must have hx-post, hx-trigger, hx-target, hx-swap."""
        try:
            template = env.get_template("taller/partials/workspace.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(**workspace_context)

        assert 'hx-post="/taller/preview/42"' in html
        assert 'hx-target="#pdf-preview"' in html
        assert 'hx-swap="innerHTML"' in html

    def test_preserves_pdf_preview_div(self, env, workspace_context):
        """PDF preview div with hx-get and hx-trigger load."""
        try:
            template = env.get_template("taller/partials/workspace.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(**workspace_context)

        assert 'id="pdf-preview"' in html
        assert 'hx-get="/taller/preview/42"' in html
        assert 'hx-trigger="load"' in html

    def test_renders_pdf_download_link(self, env, workspace_context):
        """Download PDF link with correct href."""
        try:
            template = env.get_template("taller/partials/workspace.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(**workspace_context)

        assert 'href="/reports/42/pdf"' in html
        assert "Descargar PDF" in html

    def test_patient_name_is_autoescaped(self, env, workspace_context):
        """Patient name with XSS payload must be autoescaped."""
        try:
            template = env.get_template("taller/partials/workspace.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        ctx = workspace_context.copy()
        ctx["patient"] = workspace_context["patient"].copy()
        ctx["patient"]["name"] = '<script>alert("xss")</script>'

        html = template.render(**ctx)

        assert "&lt;script&gt;" in html
        assert '<script>alert(' not in html

    def test_lab_value_raw_value_is_autoescaped(self, env, workspace_context):
        """Lab raw_value with XSS payload must be autoescaped in input value attr."""
        try:
            template = env.get_template("taller/partials/workspace.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        ctx = workspace_context.copy()
        ctx["lab_values"] = [
            {
                "parameter_code": "WBC",
                "parameter_name_es": "Leucocitos",
                "raw_value": '14.26" onclick="alert(1)',
                "unit": "10*9/L",
                "reference_range": "5.05-16.76",
                "flag": "NORMAL",
            },
        ]

        html = template.render(**ctx)

        # The raw_value in the value attribute must be escaped
        # Jinja2 autoencodes " as &#34; (numeric entity) inside attributes
        # The &#34; proves that user-supplied quotes were escaped
        assert "&#34;" in html
        # The " inside the raw_value is escaped, so it cannot create a real attribute
        assert 'onclick="alert' not in html.lower()

    def test_doctor_select_preserves_htmx_attrs(self, env, workspace_context):
        """Doctor select must have hx-post, hx-trigger, hx-target, hx-swap."""
        try:
            template = env.get_template("taller/partials/workspace.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(**workspace_context)

        assert 'hx-trigger="change"' in html
        assert 'hx-target="#pdf-preview"' in html

    def test_preserves_workspace_layout_divs(self, env, workspace_context):
        """Workspace must render both left and right panels."""
        try:
            template = env.get_template("taller/partials/workspace.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(**workspace_context)

        assert "workspace-left" in html
        assert "workspace-right" in html
        assert "patient-form" in html
        assert "lab-values-table" in html

    def test_doctor_field_with_add_button(self, env, workspace_context):
        """Doctor field must include add button with hx-get to form-add."""
        try:
            template = env.get_template("taller/partials/workspace.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(**workspace_context)

        assert 'hx-get="/taller/doctors/form-add"' in html
        assert 'id="doctor-modal"' in html

    def test_preserves_doctor_select_with_correct_id(self, env, workspace_context):
        """Doctor select DOM id must be 'doctor-select' per spec."""
        try:
            template = env.get_template("taller/partials/workspace.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(**workspace_context)

        assert 'id="doctor-select"' in html


# ══════════════════════════════════════════════════════════════════════════
# T3.1c: taller/partials/image_toggle.html
# ══════════════════════════════════════════════════════════════════════════


class TestImageToggleTemplate:
    """taller/partials/image_toggle.html — image checkbox toggle."""

    def test_template_exists(self, env):
        """Template file must exist and load without error."""
        template = env.get_template("taller/partials/image_toggle.html")
        assert template is not None

    def test_renders_checked_checkbox(self, env):
        """When checked=True, renders input with 'checked' attribute."""
        try:
            template = env.get_template("taller/partials/image_toggle.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(image_id=5, checked="checked")

        assert "checkbox" in html
        assert "checked" in html
        assert 'hx-patch="/taller/images/5/toggle"' in html
        assert 'hx-swap="outerHTML"' in html

    def test_renders_unchecked_checkbox(self, env):
        """When checked='', renders input without 'checked' attribute (triangulation)."""
        try:
            template = env.get_template("taller/partials/image_toggle.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(image_id=7, checked="")

        assert "checkbox" in html
        assert "checked" not in html  # No checked attribute when empty string

    def test_preserves_htmx_attributes(self, env):
        """Checkbox must have hx-patch and hx-swap=outerHTML."""
        try:
            template = env.get_template("taller/partials/image_toggle.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(image_id=99, checked="checked")

        assert 'hx-patch="/taller/images/99/toggle"' in html
        assert 'hx-swap="outerHTML"' in html


# ══════════════════════════════════════════════════════════════════════════
# T3.1d: taller/partials/algorithm_errors.html
# ══════════════════════════════════════════════════════════════════════════


class TestAlgorithmErrorsTemplate:
    """taller/partials/algorithm_errors.html — motor diagnosis panel."""

    def test_template_exists(self, env):
        """Template file must exist and load without error."""
        template = env.get_template("taller/partials/algorithm_errors.html")
        assert template is not None

    def test_returns_empty_for_no_errors(self, env):
        """No errors returns empty string (no HTML)."""
        try:
            template = env.get_template("taller/partials/algorithm_errors.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(errors=[])
        assert html.strip() == ""

    def test_renders_error_panel_with_errors(self, env):
        """Errors list renders diagnosis panel with algorithm names and reasons."""
        try:
            template = env.get_template("taller/partials/algorithm_errors.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        errors = [
            {"algorithm": "Na:K", "reason": "Potasio fuera de rango para caninos"},
            {"algorithm": "ALT:AST", "reason": "ALT elevado, posible daño hepático"},
        ]

        html = template.render(errors=errors)

        assert "⚠️ Diagnóstico del Motor" in html
        assert "Na:K" in html
        assert "Potasio fuera de rango para caninos" in html
        assert "ALT:AST" in html
        assert "ALT elevado" in html
        assert "motor-errors" in html

    def test_preserves_inline_styles(self, env):
        """Motor-errors panel must preserve inline styles."""
        try:
            template = env.get_template("taller/partials/algorithm_errors.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        errors = [{"algorithm": "TEST", "reason": "test reason"}]

        html = template.render(errors=errors)

        assert "background:#fffbeb" in html
        assert "border:1px solid #f59e0b" in html
        assert "border-radius:0.5rem" in html

    def test_error_reason_is_autoescaped(self, env):
        """Error reason with HTML chars must be autoescaped."""
        try:
            template = env.get_template("taller/partials/algorithm_errors.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        errors = [
            {"algorithm": "TEST", "reason": '<b>invalid</b><script>x</script>'},
        ]

        html = template.render(errors=errors)

        assert "&lt;b&gt;" in html
        assert "&lt;script&gt;" in html
        assert "<script>" not in html

    def test_multiple_errors_rendered_as_list(self, env):
        """Multiple errors render as unordered list items (triangulation)."""
        try:
            template = env.get_template("taller/partials/algorithm_errors.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        errors = [
            {"algorithm": "A", "reason": "reason A"},
            {"algorithm": "B", "reason": "reason B"},
            {"algorithm": "C", "reason": "reason C"},
        ]

        html = template.render(errors=errors)

        # Count <li> hits
        assert html.count("<li>") == 3
        assert "reason A" in html
        assert "reason B" in html
        assert "reason C" in html
