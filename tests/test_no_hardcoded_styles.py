import re
from pathlib import Path

APP_CSS = Path(__file__).resolve().parent.parent / "src/mcontrol/static/app.css"
HEX_COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def _component_css_text() -> str:
    """Concatenated text of every component CSS file (app.css and its split
    modules app.*.css), excluding tokens.css which legitimately holds the
    raw-hex primitive layer."""
    files = sorted(APP_CSS.parent.glob("app*.css"))
    assert files, "no component CSS files found next to app.css"
    return "\n".join(f.read_text(encoding="utf-8") for f in files)


def test_app_css_has_no_hardcoded_hex_colors():
    """All colors must come from tokens.css via var(--*). Component CSS is
    layout-only; app.css is an @import manifest over the app.*.css modules."""
    matches = HEX_COLOR.findall(_component_css_text())
    assert matches == [], (
        f"component CSS contains hardcoded hex colors: {matches!r}. "
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
    content = _component_css_text()
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


def test_css_var_references_resolve():
    """Every var(--x) used without a fallback must resolve to a custom
    property defined somewhere in the static CSS (tokens.css or a
    component file). Catches typo'd token names like var(--danger) or
    var(--text-sm) that the hex/font checks above cannot see: a
    misspelled var() reference is silently dead, not a parse error."""
    static_dir = APP_CSS.parent
    defined: set[str] = set()
    refs_no_fallback: set[str] = set()
    for css in static_dir.glob("*.css"):
        text = css.read_text(encoding="utf-8")
        defined |= set(re.findall(r"(--[a-zA-Z0-9-]+)\s*:", text))
        for name, fallback in re.findall(
            r"var\(\s*(--[a-zA-Z0-9-]+)\s*(,)?", text
        ):
            if not fallback:
                refs_no_fallback.add(name)
    undefined = sorted(refs_no_fallback - defined)
    assert undefined == [], (
        f"CSS references undefined custom properties: {undefined!r}. "
        "Define them in tokens.css, or add a var(--x, fallback)."
    )
