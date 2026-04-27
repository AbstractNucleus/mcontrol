import re
from pathlib import Path

APP_CSS = Path("src/mcontrol/static/app.css")
HEX_COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def test_app_css_has_no_hardcoded_hex_colors():
    """All colors must come from tokens.css via var(--*). app.css is layout-only."""
    assert APP_CSS.exists(), "app.css should exist after Task 7"
    content = APP_CSS.read_text(encoding="utf-8")
    matches = HEX_COLOR.findall(content)
    assert matches == [], (
        f"app.css contains hardcoded hex colors: {matches!r}. "
        "Use var(--main-color) etc. from tokens.css instead."
    )


def test_app_css_has_no_font_family():
    """Font stacks are owned by tokens.css. app.css is layout-only."""
    content = APP_CSS.read_text(encoding="utf-8")
    assert "font-family" not in content, (
        "app.css must not declare font-family; the body declaration in tokens.css is canonical."
    )
