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
