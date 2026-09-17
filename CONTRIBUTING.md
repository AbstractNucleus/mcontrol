# Contributing

## Development

```sh
uv sync
uv run uvicorn dev_mock:app --reload --port 8000
```

The preview seeds fake servers under `.localdev/minecraft/`. Set `MCONTROL_MOCK_BASE` to choose another directory. Use the mock for interface work and test writes.

For real services, copy `.env.example` to `.env`, configure the required settings, and run `uv run uvicorn mcontrol.main:app --reload --port 8000`. The mcontrol runtime needs Supabase, Docker, and the server directory.

## Checks

```sh
uv run pytest -q
uv run ruff check .
```

Tests mock database and Docker calls. Neither service is needed for the default suite. Some filesystem checks require POSIX features and skip on Windows.

For interface changes, install Chromium once and run the relevant browser tests:

```sh
uv run playwright install chromium
MCONTROL_BROWSER_TESTS=1 uv run pytest tests/browser -q
```

In PowerShell:

```powershell
$env:MCONTROL_BROWSER_TESTS='1'
uv run pytest tests/browser -q
Remove-Item Env:MCONTROL_BROWSER_TESTS
```

Browser fixtures start an isolated mock process and use temporary server files. Screenshots go to `.localdev/ui-review/`. Review desktop and phone layouts, keyboard access, and changed interactions. Tests cover navigation, saved layouts, editing conflicts, uploads, archives, and failure recovery. They do not prove real Docker or Supabase connectivity; use `/healthz` when checking a deployment.

## Project structure

- `src/mcontrol/main.py`: shared app setup.
- `src/mcontrol/dashboards.py`: dashboard definition, route registration, and lifecycle handling.
- `src/mcontrol/mcontrol_dashboard.py`: mcontrol's routes, page context, and Docker startup/shutdown.
- `src/mcontrol/templates/`: Jinja pages and partials; `base.html` is the Dash shell and `mcontrol_base.html` adds Minecraft navigation and assets.
- `src/mcontrol/static/`: shared design tokens and browser assets. CodeMirror and fonts are vendored to avoid runtime CDN dependencies.
- `src/mcontrol/routes/`: mcontrol HTTP handlers.
- `src/mcontrol/services/` and `domain/`: mcontrol operations and rules.
- `src/mcontrol/infra/`: database, Docker, filesystem, and network adapters.
- `tests/`: unit and route tests; `tests/browser/` holds opt-in browser checks.
- `dev_mock.py`: preview adapters and fixture data.
- `deploy/`: production Compose configuration and runbook.

The `mcontrol` package name is retained for existing imports and deployment commands. Dash is the shared app; mcontrol is its first dashboard.

## Add a dashboard

Create a module that exports a `Dashboard` and an `APIRouter`. Give new dashboards their own URL prefix so they do not collide with existing mcontrol routes:

```python
from fastapi import APIRouter, Request

from mcontrol.dashboards import Dashboard
from mcontrol.templates import templates

router = APIRouter(prefix="/notes")


@router.get("")
async def home(request: Request):
    return templates.TemplateResponse(
        request=request, name="notes/home.html", context={}
    )


dashboard = Dashboard(
    id="notes", label="Notes", href="/notes", icon="grid", router=router
)
```

Add `templates/notes/home.html`:

```jinja
{% extends "base.html" %}
{% block title %}Notes | Dash{% endblock %}
{% block main %}
  <h1 class="t-h1">Notes</h1>
{% endblock %}
```

Import the definition in `main.py` and add it beside `mcontrol_dashboard` in `create_app`'s default collection. This registers its routes and adds the sidebar entry. Tests can pass an explicit collection to `create_app(dashboards=(...))` without changing the defaults. Dashboard IDs must be unique; route registration order is preserved.

Use the icons defined in `templates/_icons.html`. A dashboard may provide an async `page_context(request)` returning a mapping for its full HTML pages, and an async context-manager `lifespan(app)` for resources it owns. Neither is required for a simple dashboard. Templates read the prepared mapping through `dashboard_context(request)`. Keep external calls out of Jinja rendering.

New dashboards extend `base.html`. Add dashboard CSS in `dashboard_styles`, page scripts in `head_scripts`, and optional local navigation in `dashboard_nav`. Asset URLs use `?v={{ version }}` for cache invalidation. mcontrol pages extend `mcontrol_base.html`. To add an mcontrol route, register it in `mcontrol_dashboard.py`; `/servers/new` must stay ahead of `/servers/{name}`.

Test the new route, sidebar selection, and failure behavior with fake external dependencies. Also verify it does not fetch mcontrol data or load mcontrol assets. The deployment still requires the existing mcontrol settings; this registration interface does not rename packages or change host configuration.

## Conventions

- Keep HTTP handlers thin. Put behavior in a module with a small interface and test it through that interface.
- Keep dashboard-specific data fetching, scripts, styles, and navigation out of the shared shell.
- Use semantic variables from `static/tokens.css`. Do not add inline styles or raw colors to templates; add new colors to the semantic token layer.
- Mock external collaborators in tests. Follow `tests/conftest.py` and existing route tests for dependency injection and `monkeypatch` examples.
- Preserve routes and saved browser settings when reorganizing code.
- Keep comments for non-obvious constraints and decisions. Avoid old task numbers, progress reports, and explanations that merely restate the code.
- Change only what the task needs. Preserve unrelated user edits.

Release and rollback instructions live in [deploy/README.md](deploy/README.md).
