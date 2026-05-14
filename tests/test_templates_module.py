"""Verify the shared Jinja2Templates instance is a single object reused by all routes."""

from mcontrol import templates as templates_module
from mcontrol.routes import home, server


def test_shared_templates_object_is_used_by_home_and_server():
    # Both route modules consume the shared instance — not a per-module instance.
    assert home.templates is templates_module.templates
    assert server.templates is templates_module.templates


def test_templates_directory_resolves_to_packaged_templates():
    expected_dir = templates_module.TEMPLATES_DIR
    assert expected_dir.is_dir(), f"templates dir {expected_dir} should exist"
    assert (expected_dir / "base.html").is_file()


def test_flash_partial_uses_alert_role_for_errors():
    # Error flashes need assertive announcement — the polite #flash-stack
    # container won't drive that, so the individual message carries
    # role="alert" to upgrade.
    html = templates_module.templates.get_template("_flash.html").render(
        flash={"kind": "error", "message": "boom"}
    )
    assert 'role="alert"' in html
    assert 'role="status"' not in html
    assert "flash-msg--error" in html


def test_flash_partial_uses_status_role_for_ok_and_info():
    # Success / info should announce politely via the live region, not
    # interrupt the user — so role="status", never role="alert".
    for kind in ("ok", "info"):
        html = templates_module.templates.get_template("_flash.html").render(
            flash={"kind": kind, "message": "hello"}
        )
        assert 'role="status"' in html, kind
        assert 'role="alert"' not in html, kind
        assert f"flash-msg--{kind}" in html, kind


def test_flash_partial_dismiss_button_has_aria_label():
    # The "×" button has no visible text screen readers can use, so it
    # carries an explicit aria-label.
    html = templates_module.templates.get_template("_flash.html").render(
        flash={"kind": "ok", "message": "hello"}
    )
    assert 'aria-label="Dismiss"' in html


def test_base_flash_stack_is_a_polite_live_region():
    # Container is polite by default; individual error messages upgrade
    # to assertive via their own role="alert".
    html = templates_module.templates.get_template("base.html").render(version="x")
    assert 'id="flash-stack"' in html
    assert 'aria-live="polite"' in html
