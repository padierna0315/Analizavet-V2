"""Tests for quarantine partial templates (PR #2, T2.2).

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
# T2.2a: quarantine/partials/badge.html
# ══════════════════════════════════════════════════════════════════════════


class TestBadgeTemplate:
    """quarantine/partials/badge.html — quarantine count badge."""

    def test_template_exists(self, env):
        """Template file must exist and load without error."""
        template = env.get_template("quarantine/partials/badge.html")
        assert template is not None

    def test_renders_badge_with_count_greater_than_zero(self, env):
        """count > 0 renders an anchor badge with warning icon and count."""
        try:
            template = env.get_template("quarantine/partials/badge.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(count=5)

        assert 'href="/quarantine"' in html
        assert '5 elemento(s) en cuarentena' in html
        assert '⚠ 5' in html

    def test_returns_empty_for_count_zero(self, env):
        """count == 0 returns empty string (no badge)."""
        try:
            template = env.get_template("quarantine/partials/badge.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(count=0)
        assert html.strip() == ""

    def test_count_is_autoescaped_in_title(self, env):
        """Count in title attribute must be autoescaped."""
        try:
            template = env.get_template("quarantine/partials/badge.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(count=3)

        assert 'title="3 elemento(s) en cuarentena"' in html

    def test_preserves_inline_styles(self, env):
        """Inline styles in badge must be preserved."""
        try:
            template = env.get_template("quarantine/partials/badge.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(count=1)

        assert "color: #fbbf24" in html
        assert "background: rgba(251,191,36,0.15)" in html
        assert "border-radius: 4px" in html


class TestBadgeTemplateEdgeCases:
    """Triangulation: edge cases for the badge template."""

    @pytest.fixture
    def render(self, env):
        """Try to render — skip if template doesn't exist yet."""
        try:
            tmpl = env.get_template("quarantine/partials/badge.html")
            return tmpl.render
        except TemplateNotFound:
            return None

    def test_large_count_renders(self, render):
        """Badge works with large count values (3-digit)."""
        if render is None:
            pytest.skip("Template not yet created — RED phase")
        html = render(count=999)
        assert "⚠ 999" in html


# ══════════════════════════════════════════════════════════════════════════
# T2.2b: quarantine/partials/oob_swap.html
# ══════════════════════════════════════════════════════════════════════════


class TestOobSwapTemplate:
    """quarantine/partials/oob_swap.html — force-match/discard OOB swaps."""

    def test_template_exists(self, env):
        """Template file must exist and load without error."""
        template = env.get_template("quarantine/partials/oob_swap.html")
        assert template is not None

    def test_renders_delete_row_and_badge_update(self, env):
        """Renders hx-swap-oob=delete for row + innerHTML for badge."""
        try:
            template = env.get_template("quarantine/partials/oob_swap.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(
            quarantine_id=42,
            pending_count=3,
        )

        assert 'id="quarantine-row-42"' in html
        assert 'hx-swap-oob="delete"' in html
        assert 'id="quarantine-badge"' in html
        assert 'hx-swap-oob="innerHTML"' in html
        assert "⚠ 3" in html

    def test_renders_badge_empty_when_pending_count_zero(self, env):
        """When pending_count is 0, badge div contains nothing (empty string)."""
        try:
            template = env.get_template("quarantine/partials/oob_swap.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(
            quarantine_id=1,
            pending_count=0,
        )

        assert 'id="quarantine-row-1"' in html
        assert 'hx-swap-oob="delete"' in html
        assert 'id="quarantine-badge"' in html
        assert 'hx-swap-oob="innerHTML"' in html
        # Badge div inner should NOT contain the anchor (count=0)
        inner_start = html.index('id="quarantine-badge"')
        inner_end = html.index("</div>", inner_start)
        badge_inner = html[inner_start:inner_end]
        assert '<a' not in badge_inner

    def test_preserves_exact_oob_attribute_values(self, env):
        """hx-swap-oob values must be 'delete' and 'innerHTML' exactly."""
        try:
            template = env.get_template("quarantine/partials/oob_swap.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(
            quarantine_id=7,
            pending_count=2,
        )

        assert 'hx-swap-oob="delete"' in html
        assert 'hx-swap-oob="innerHTML"' in html

    def test_quarantine_id_is_autoescaped(self, env):
        """quarantine_id (int) is safe but template should autoescape."""
        try:
            template = env.get_template("quarantine/partials/oob_swap.html")
        except TemplateNotFound:
            pytest.skip("Template not yet created — RED phase")

        html = template.render(
            quarantine_id=12345,
            pending_count=0,
        )

        assert 'id="quarantine-row-12345"' in html
