import re
from pathlib import Path

APP_CSS = Path(__file__).resolve().parent.parent / "src/mcontrol/static/app.css"
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


def test_app_css_font_family_uses_tokens_only():
    """Font stacks are owned by tokens.css. Components in app.css may
    set `font-family` only to `var(--font-*)` or `inherit`: never a
    literal font name. Slice 12 swap relaxed slice 1's
    "no font-family in app.css at all" invariant once mono surfaces
    (logs, code, file tree) needed an explicit deviation from the
    sans body default; the tokens-only rule preserves the original
    intent (token layer is the single source of truth for type)."""
    content = APP_CSS.read_text(encoding="utf-8")
    # Capture every `font-family: <value>;` declaration.
    decls = re.findall(r"font-family\s*:\s*([^;]+);", content)
    bad = [
        d.strip()
        for d in decls
        if not (d.strip() == "inherit" or d.strip().startswith("var(--font-"))
    ]
    assert bad == [], (
        f"app.css has literal font-family value(s) {bad!r}. "
        "Use var(--font-sans) / var(--font-mono) from tokens.css instead."
    )
