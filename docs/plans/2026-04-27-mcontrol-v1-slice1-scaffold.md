# mcontrol v1 — Slice 1: Project Scaffold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a deployable FastAPI + Jinja + HTMX skeleton, themed entirely from the AbstractNucleus/design tokens, served behind Caddy with the tailnet-only TLS pattern. No Docker socket integration, no Supabase, no business logic — those land in later slices.

**Architecture:** A single Python service. uvicorn runs FastAPI; FastAPI renders Jinja templates against `tokens.css` vendored from `AbstractNucleus/design`. The skeleton is containerized and shipped behind Caddy via docker-compose, following `docs/patterns/tailnet-https-via-cloudflare.md`. HTMX is wired in but unused this slice — subsequent slices attach `hx-*` attributes.

**Tech Stack:** Python 3.12, FastAPI, uvicorn[standard], Jinja2, pydantic-settings; pytest + pytest-asyncio + httpx for tests; ruff for lint; uv for dependency/lockfile management. Docker + docker-compose. Caddy via `slothcroissant/caddy-cloudflaredns:latest`.

---

## Scope of this plan

This plan delivers **Slice 1 of v1 only — the scaffold**. Subsequent slices each get their own plan, written after the previous one lands:

| Slice | Scope | Plan |
|---|---|---|
| 1 | Scaffold (this plan) | This document |
| 2 | Supabase migration for `app_mcontrol` schema | Lives in `supabase-server` repo (decision 015) |
| 3 | Server discovery + read-only server list | TBD |
| 4 | Start/Stop/Restart + log SSE + RCON console | TBD |
| 5 | File browser + editor + jar/mod uploads | TBD |
| 6 | New-server scaffolding flow | TBD |
| 7 | Whitelist + ops UI | TBD |
| 8 | itzg → temurin migration for `atm10` + `monifactory` | TBD |

This split honours the writing-plans rule that each plan should produce working, testable software on its own.

## Decisions register references

This slice acts on:
- **016** Backend stack: FastAPI + Jinja + HTMX
- **002** UI palette: AbstractNucleus/design (tokens.css)
- **003** Tailnet-only access via Cloudflare DNS-01

Deferred to later slices: 005, 006, 007, 008, 009, 010, 011, 012, 013, 014, 015, 017, 018.

## Assumptions (surfaced, not buried)

1. The repo is developed on Windows (`D:\code\mcontrol`) but deployed on Linux (bserver). Python code is OS-agnostic; Dockerfiles, shell scripts, and template files use Linux conventions.
2. CF_API_TOKEN with `Zone:DNS:Edit` scope on `noelkleen.com` already exists (per the existing tailnet pattern in `admin_management`). Slice 1 does not provision it.
3. Hostname `mcontrol.noelkleen.com` will get a gray-cloud A record pointing at bserver's tailnet IP before first deploy. Slice 1 ships the Caddyfile but does not perform DNS work.
4. Port conflicts on bserver (e.g. with `admin-dashboard` on :8000) are a deployment-time concern. Slice 1's container exposes :8000 internally; the host port mapping is finalised at deploy.
5. Tailnet TLS cannot be end-to-end verified from Windows dev (no tailnet IP routing to localhost). Slice 1 verifies the container starts and `/healthz` responds; full TLS verification happens at first bserver deploy.

## File structure for v1 (slice 1 touches only files marked **§1**)

```
mcontrol/
├── pyproject.toml                               §1
├── .python-version                              §1
├── uv.lock                                      §1 (generated)
├── .env.example                                 §1
├── .gitignore                                   §1 (modify)
├── README.md                                    §1 (modify)
├── Dockerfile                                   §1
├── docker-compose.yml                           §1
├── Caddyfile                                    §1
├── docs/                                        (existing)
├── research/                                    (existing)
├── scripts/
│   └── sync_design.sh                           §1
├── src/
│   └── mcontrol/
│       ├── __init__.py                          §1
│       ├── main.py                              §1
│       ├── settings.py                          §1
│       ├── db.py                                §3
│       ├── docker_client.py                     §3
│       ├── rcon.py                              §4
│       ├── filesystem.py                        §5
│       ├── templates_gen.py                     §6
│       ├── routes/
│       │   ├── __init__.py                      §1
│       │   ├── home.py                          §1
│       │   ├── server.py                        §3
│       │   ├── lifecycle.py                     §4
│       │   ├── logs.py                          §4
│       │   ├── console.py                       §4
│       │   ├── files.py                         §5
│       │   ├── new_server.py                    §6
│       │   └── whitelist_ops.py                 §7
│       ├── templates/
│       │   ├── base.html                        §1
│       │   └── home.html                        §1
│       └── static/
│           ├── tokens.css                       §1 (vendored)
│           ├── app.css                          §1
│           ├── htmx.min.js                      §1 (vendored)
│           └── htmx-ext-sse.js                  §1 (vendored)
└── tests/
    ├── __init__.py                              §1
    ├── conftest.py                              §1
    ├── test_healthz.py                          §1
    ├── test_home.py                             §1
    └── test_static.py                           §1
```

---

# Pre-flight

- [ ] **P1: Create a feature branch**

```bash
git checkout -b slice1-scaffold
```

- [ ] **P2: Sanity check working tree is clean**

Run: `git status`
Expected: `nothing to commit, working tree clean` (the new branch starts from `main` which is clean per the session brief).

- [ ] **P3: Confirm `uv` is installed**

Run: `uv --version`
Expected: a version string like `uv 0.5.x` or higher. If not present, install per https://docs.astral.sh/uv/getting-started/installation/.

---

# Task 1: Bootstrap Python project with `uv`

**Files:**
- Create: `pyproject.toml`
- Create: `.python-version`
- Create: `uv.lock` (generated)

- [ ] **Step 1: Pin Python version**

Create `.python-version`:

```
3.12
```

- [ ] **Step 2: Create `pyproject.toml`**

```toml
[project]
name = "mcontrol"
version = "0.1.0"
description = "Minecraft + Docker control panel for a single host."
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "jinja2>=3.1",
    "pydantic>=2.9",
    "pydantic-settings>=2.6",
]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "httpx>=0.27",
    "ruff>=0.7",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/mcontrol"]
```

- [ ] **Step 3: Resolve and lock**

Run: `uv sync`
Expected: creates `.venv/`, generates `uv.lock`, exits 0. Output ends with `Resolved N packages` and `Installed N packages`.

- [ ] **Step 4: Smoke-check the venv**

Run: `uv run python -c "import fastapi, uvicorn, jinja2, pydantic_settings; print('ok')"`
Expected: `ok`.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .python-version uv.lock
git commit -m "chore: bootstrap python project with uv (slice 1)"
```

---

# Task 2: Settings module

**Files:**
- Create: `src/mcontrol/__init__.py`
- Create: `src/mcontrol/settings.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Test: `tests/test_settings.py`

- [ ] **Step 1: Create empty package files**

Create `src/mcontrol/__init__.py`:

```python
"""mcontrol — Minecraft + Docker control panel."""

__version__ = "0.1.0"
```

Create `tests/__init__.py`:

```python
```

(empty)

- [ ] **Step 2: Write the failing test**

Create `tests/test_settings.py`:

```python
import pytest

from mcontrol.settings import Settings


def test_settings_load_from_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://api.noelkleen.com")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")
    monkeypatch.setenv("SERVER_BASE_PATH", "/home/abstract/servers/minecraft")

    settings = Settings()

    assert settings.supabase_url == "https://api.noelkleen.com"
    assert settings.supabase_service_role_key == "test-key"
    assert settings.server_base_path == "/home/abstract/servers/minecraft"


def test_settings_missing_required_field_raises(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("SERVER_BASE_PATH", raising=False)

    with pytest.raises(Exception):
        Settings(_env_file=None)
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/test_settings.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mcontrol.settings'`.

- [ ] **Step 4: Write the minimal implementation**

Create `src/mcontrol/settings.py`:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    supabase_url: str
    supabase_service_role_key: str
    server_base_path: str
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_settings.py -v`
Expected: 2 passed.

- [ ] **Step 6: Create the conftest with the FastAPI test client fixture**

Create `tests/conftest.py`:

```python
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def env(monkeypatch):
    """Default test environment — required Settings fields populated."""
    monkeypatch.setenv("SUPABASE_URL", "https://api.noelkleen.com")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")
    monkeypatch.setenv("SERVER_BASE_PATH", "/tmp/mcontrol-test-servers")


@pytest.fixture
async def client(env) -> AsyncIterator[AsyncClient]:
    from mcontrol.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
```

- [ ] **Step 7: Commit**

```bash
git add src/mcontrol/__init__.py src/mcontrol/settings.py tests/__init__.py tests/conftest.py tests/test_settings.py
git commit -m "feat(settings): pydantic-settings module loading from env"
```

---

# Task 3: FastAPI app factory + healthcheck

**Files:**
- Create: `src/mcontrol/main.py`
- Test: `tests/test_healthz.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_healthz.py`:

```python
async def test_healthz_returns_ok(client):
    response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_healthz.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mcontrol.main'`.

- [ ] **Step 3: Write the minimal implementation**

Create `src/mcontrol/main.py`:

```python
from fastapi import FastAPI

from mcontrol.settings import Settings


def create_app() -> FastAPI:
    settings = Settings()
    app = FastAPI(title="mcontrol", version="0.1.0")
    app.state.settings = settings

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_healthz.py -v`
Expected: 1 passed.

- [ ] **Step 5: Smoke-run the app locally**

Run: `uv run uvicorn mcontrol.main:app --port 8000 --env-file .env.example` (after Task 9 creates `.env.example`; for now, set the env vars inline)

Or, with env vars on the shell, run: `SUPABASE_URL=https://api.noelkleen.com SUPABASE_SERVICE_ROLE_KEY=x SERVER_BASE_PATH=/tmp/x uv run uvicorn mcontrol.main:app --port 8000`

In another terminal: `curl -s http://localhost:8000/healthz`
Expected: `{"status":"ok"}`

Stop the server (Ctrl+C).

- [ ] **Step 6: Commit**

```bash
git add src/mcontrol/main.py tests/test_healthz.py
git commit -m "feat(app): fastapi app factory with /healthz"
```

---

# Task 4: Vendor `tokens.css` from AbstractNucleus/design

**Files:**
- Create: `src/mcontrol/static/tokens.css`
- Create: `scripts/sync_design.sh`

- [ ] **Step 1: Make the static dir**

```bash
mkdir -p src/mcontrol/static
```

- [ ] **Step 2: Vendor tokens.css**

Run:

```bash
gh api repos/AbstractNucleus/design/contents/tokens.css --jq .content | base64 -d > src/mcontrol/static/tokens.css
```

Expected: file written, no errors.

- [ ] **Step 3: Verify the file contents**

Run: `head -5 src/mcontrol/static/tokens.css`
Expected: starts with `/* =========================================================================`

Run: `grep -c -- '--main-color: #b5533a' src/mcontrol/static/tokens.css`
Expected: `1`

- [ ] **Step 4: Create the sync script for future updates**

Create `scripts/sync_design.sh`:

```bash
#!/usr/bin/env bash
# Re-pull tokens.css from AbstractNucleus/design.
# Run when the upstream tokens are updated and you want mcontrol to track.

set -euo pipefail

cd "$(dirname "$0")/.."

gh api repos/AbstractNucleus/design/contents/tokens.css --jq .content \
    | base64 -d \
    > src/mcontrol/static/tokens.css

echo "Synced tokens.css ($(wc -l < src/mcontrol/static/tokens.css) lines)"
```

- [ ] **Step 5: Make it executable**

Run: `chmod +x scripts/sync_design.sh`
Expected: no output, no error.

- [ ] **Step 6: Commit**

```bash
git add src/mcontrol/static/tokens.css scripts/sync_design.sh
git commit -m "feat(design): vendor tokens.css from AbstractNucleus/design"
```

---

# Task 5: Static file mount + tokens.css served

**Files:**
- Modify: `src/mcontrol/main.py`
- Test: `tests/test_static.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_static.py`:

```python
async def test_tokens_css_is_served(client):
    response = await client.get("/static/tokens.css")

    assert response.status_code == 200
    assert "--main-color: #b5533a" in response.text
    assert response.headers["content-type"].startswith("text/css")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_static.py -v`
Expected: FAIL with status 404.

- [ ] **Step 3: Mount static files in the app factory**

Edit `src/mcontrol/main.py` — add the `StaticFiles` mount inside `create_app`:

```python
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from mcontrol.settings import Settings

STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    settings = Settings()
    app = FastAPI(title="mcontrol", version="0.1.0")
    app.state.settings = settings

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_static.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/mcontrol/main.py tests/test_static.py
git commit -m "feat(app): mount /static and serve tokens.css"
```

---

# Task 6: Base template + home page

**Files:**
- Create: `src/mcontrol/templates/base.html`
- Create: `src/mcontrol/templates/home.html`
- Create: `src/mcontrol/routes/__init__.py`
- Create: `src/mcontrol/routes/home.py`
- Modify: `src/mcontrol/main.py`
- Test: `tests/test_home.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_home.py`:

```python
async def test_home_renders_wordmark(client):
    response = await client.get("/")

    assert response.status_code == 200
    body = response.text
    assert "mcontrol" in body
    # tokens.css is the only color/type/spacing source — verify it's linked
    assert '/static/tokens.css' in body
    # app.css applies layout — verify it's linked
    assert '/static/app.css' in body


async def test_home_shows_empty_state(client):
    response = await client.get("/")

    # Slice 1 has no real server data; an empty-state message is expected.
    assert response.status_code == 200
    assert "No servers yet" in response.text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_home.py -v`
Expected: FAIL with status 404 (route not registered yet).

- [ ] **Step 3: Create the base template**

Create `src/mcontrol/templates/base.html`:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}mcontrol{% endblock %}</title>
  <link rel="stylesheet" href="/static/tokens.css">
  <link rel="stylesheet" href="/static/app.css">
  <script src="/static/htmx.min.js" defer></script>
  <script src="/static/htmx-ext-sse.js" defer></script>
</head>
<body>
  <header class="page-header">
    <h1 class="t-h2">mcontrol</h1>
    <span class="t-caption">v{{ version }}</span>
  </header>
  <main class="page-main">
    {% block main %}{% endblock %}
  </main>
</body>
</html>
```

- [ ] **Step 4: Create the home template**

Create `src/mcontrol/templates/home.html`:

```html
{% extends "base.html" %}

{% block title %}mcontrol — servers{% endblock %}

{% block main %}
<section>
  <p class="t-eyebrow">Servers</p>
  <div class="card">
    <p class="t-body">No servers yet — discovery lands in slice 3.</p>
  </div>
</section>
{% endblock %}
```

- [ ] **Step 5: Create the home route**

Create `src/mcontrol/routes/__init__.py`:

```python
```

(empty)

Create `src/mcontrol/routes/home.py`:

```python
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from mcontrol import __version__

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"version": __version__},
    )
```

- [ ] **Step 6: Wire the router into the app**

Edit `src/mcontrol/main.py` — register the router:

```python
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from mcontrol.routes import home
from mcontrol.settings import Settings

STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    settings = Settings()
    app = FastAPI(title="mcontrol", version="0.1.0")
    app.state.settings = settings

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(home.router)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `uv run pytest tests/test_home.py -v`
Expected: 2 passed.

- [ ] **Step 8: Run the full test suite as a regression check**

Run: `uv run pytest -v`
Expected: 5 passed (settings ×2, healthz ×1, static ×1, home ×2 — actually 6).

- [ ] **Step 9: Commit**

```bash
git add src/mcontrol/templates/ src/mcontrol/routes/ src/mcontrol/main.py tests/test_home.py
git commit -m "feat(home): jinja base template + home page with empty state"
```

---

# Task 7: app.css layout shell + hardcoded-color guard

**Files:**
- Create: `src/mcontrol/static/app.css`
- Test: `tests/test_no_hardcoded_styles.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_no_hardcoded_styles.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_no_hardcoded_styles.py -v`
Expected: FAIL with `assert APP_CSS.exists()` failing because the file does not exist.

- [ ] **Step 3: Create app.css with layout-only rules**

Create `src/mcontrol/static/app.css`:

```css
/* mcontrol — layout-only rules. All color, type, and spacing values come from tokens.css. */

body {
  margin: 0;
}

.page-header {
  display: flex;
  align-items: baseline;
  gap: var(--space-3);
  padding: var(--space-8) var(--space-16);
  border-bottom: 1px solid var(--sub-alt-color);
}

.page-main {
  max-width: 1280px;
  margin: 0 auto;
  padding: var(--space-12) var(--space-16);
  display: flex;
  flex-direction: column;
  gap: var(--space-12);
}

@media (max-width: 768px) {
  .page-header,
  .page-main {
    padding-left: var(--space-6);
    padding-right: var(--space-6);
  }
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_no_hardcoded_styles.py -v`
Expected: 2 passed.

- [ ] **Step 5: Visual sanity check**

Run: `SUPABASE_URL=x SUPABASE_SERVICE_ROLE_KEY=x SERVER_BASE_PATH=/tmp uv run uvicorn mcontrol.main:app --port 8000`

Open `http://localhost:8000/` in a browser. Verify:
- Background is bone paper (`#f1ece2`).
- "mcontrol" wordmark is in monospace, walnut ink.
- "v0.1.0" caption is quiet ink, smaller, with caps-letter spacing visually different from the heading.
- The empty-state card is on a tinted surface (`#e6dfd0`) with rounded corners.
- No browser-blue focus rings appear when tabbing.

If any of these fail, the tokens link or app.css layout is wrong — fix before continuing.

Stop the server (Ctrl+C).

- [ ] **Step 6: Commit**

```bash
git add src/mcontrol/static/app.css tests/test_no_hardcoded_styles.py
git commit -m "feat(design): app.css layout shell + hardcoded-style guard"
```

---

# Task 8: Vendor HTMX + SSE extension

**Files:**
- Create: `src/mcontrol/static/htmx.min.js`
- Create: `src/mcontrol/static/htmx-ext-sse.js`
- Test: extend `tests/test_static.py`

- [ ] **Step 1: Vendor HTMX 2.x**

Run:

```bash
curl -fsSL https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js -o src/mcontrol/static/htmx.min.js
curl -fsSL https://unpkg.com/htmx-ext-sse@2.2.2/sse.js -o src/mcontrol/static/htmx-ext-sse.js
```

Expected: both files written, exit 0. (If a newer HTMX 2.x or SSE extension is available, prefer it; the only requirement is that they ship together.)

- [ ] **Step 2: Verify the files are non-empty and look right**

Run: `wc -c src/mcontrol/static/htmx.min.js src/mcontrol/static/htmx-ext-sse.js`
Expected: htmx.min.js > 30000 bytes; sse.js > 1000 bytes.

Run: `head -c 200 src/mcontrol/static/htmx.min.js`
Expected: contains the string `htmx`.

- [ ] **Step 3: Extend the static test**

Edit `tests/test_static.py` — add:

```python
async def test_htmx_is_served(client):
    response = await client.get("/static/htmx.min.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(("application/javascript", "text/javascript"))
    assert len(response.content) > 30_000


async def test_htmx_sse_extension_is_served(client):
    response = await client.get("/static/htmx-ext-sse.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(("application/javascript", "text/javascript"))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_static.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/mcontrol/static/htmx.min.js src/mcontrol/static/htmx-ext-sse.js tests/test_static.py
git commit -m "feat(htmx): vendor htmx 2.x core + sse extension"
```

---

# Task 9: Dockerfile, docker-compose, Caddyfile, .env.example

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `Caddyfile`
- Create: `.env.example`
- Modify: `.gitignore`

- [ ] **Step 1: Create the Dockerfile**

Create `Dockerfile`:

```dockerfile
# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# uv is the lockfile/dep tool; copy it from the official image.
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /usr/local/bin/

WORKDIR /app

# Install deps first for cache friendliness.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ ./src/

# Install the project itself (editable metadata only; src is already there).
RUN uv sync --frozen --no-dev

EXPOSE 8000

CMD ["uv", "run", "--no-dev", "uvicorn", "mcontrol.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Create the Caddyfile**

Create `Caddyfile`:

```caddy
# Tailnet-only TLS via Cloudflare DNS-01.
# See docs/patterns/tailnet-https-via-cloudflare.md.
mcontrol.noelkleen.com {
  tls {
    dns cloudflare {env.CF_API_TOKEN}
  }
  reverse_proxy app:8000
}
```

- [ ] **Step 3: Create the docker-compose**

Create `docker-compose.yml`:

```yaml
services:
  app:
    build: .
    restart: unless-stopped
    env_file: .env
    expose:
      - "8000"
    networks:
      - internal

  caddy:
    image: slothcroissant/caddy-cloudflaredns:latest
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    environment:
      CF_API_TOKEN: ${CF_API_TOKEN}
    depends_on:
      - app
    networks:
      - internal

networks:
  internal:

volumes:
  caddy_data:
  caddy_config:
```

- [ ] **Step 4: Create .env.example**

Create `.env.example`:

```bash
# mcontrol — copy to .env and fill in.

# Supabase (shared, on bserver). Service-role key is server-side only (decision 011).
SUPABASE_URL=https://api.noelkleen.com
SUPABASE_SERVICE_ROLE_KEY=

# Where minecraft server directories live on the host (decision 008).
SERVER_BASE_PATH=/home/abstract/servers/minecraft

# Cloudflare API token with Zone:DNS:Edit on noelkleen.com — used by Caddy
# for the DNS-01 ACME challenge (decision 003 + docs/patterns/tailnet-https-via-cloudflare.md).
CF_API_TOKEN=
```

- [ ] **Step 5: Update .gitignore**

Read `.gitignore` first:

```bash
cat .gitignore 2>/dev/null || true
```

If it doesn't already cover Python + .env, append (or create):

```
# Python
__pycache__/
*.py[cod]
.venv/
.pytest_cache/
.ruff_cache/

# Environment
.env

# Editor / OS
.idea/
.vscode/
.DS_Store
Thumbs.db
```

- [ ] **Step 6: Build the image locally**

Run: `docker compose build app`
Expected: build succeeds; final image tagged. If `docker compose` is unavailable on Windows, use `docker-compose` (hyphenated) or run inside WSL2.

- [ ] **Step 7: Smoke-test the container without Caddy**

Run:

```bash
docker compose run --rm -e SUPABASE_URL=https://api.noelkleen.com -e SUPABASE_SERVICE_ROLE_KEY=x -e SERVER_BASE_PATH=/tmp -p 8000:8000 app
```

In another terminal: `curl -s http://localhost:8000/healthz`
Expected: `{"status":"ok"}`

Stop the container (Ctrl+C).

(Caddy + tailnet TLS is verified at first bserver deploy, not in this slice — see Assumption 5.)

- [ ] **Step 8: Commit**

```bash
git add Dockerfile docker-compose.yml Caddyfile .env.example .gitignore
git commit -m "feat(deploy): dockerfile + compose + caddy tailnet tls"
```

---

# Task 10: README + verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Read the current README**

Run: `cat README.md`
Expected: the existing 4-line README pointing at research/ and decisions.md.

- [ ] **Step 2: Append a "Local development" and "Deployment" section**

Edit `README.md` to keep its existing top section, and append:

```markdown
## Local development

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env  # then edit .env with real values
uv run uvicorn mcontrol.main:app --reload --port 8000
```

Visit `http://localhost:8000/` for the home page and `http://localhost:8000/healthz` for a status check.

Run tests:

```bash
uv run pytest -v
```

Lint:

```bash
uv run ruff check .
```

Re-pull the AbstractNucleus design tokens:

```bash
./scripts/sync_design.sh
```

## Deployment

The default deployment shape is Docker + Caddy, with Caddy obtaining a Let's Encrypt cert via Cloudflare DNS-01 over the tailnet — see [`docs/patterns/tailnet-https-via-cloudflare.md`](docs/patterns/tailnet-https-via-cloudflare.md).

```bash
docker compose up -d --build
```

Pre-requisites on the host:
- `mcontrol.noelkleen.com` DNS A record (gray cloud) pointing at the host's tailnet IP.
- `CF_API_TOKEN` env var with `Zone:DNS:Edit` scope on `noelkleen.com`.
- Tailscale running on the host.

The container exposes :8000 internally; Caddy fronts it on :80 / :443.
```

- [ ] **Step 3: Run lint as a final check**

Run: `uv run ruff check .`
Expected: `All checks passed!` (or the equivalent ruff success message).

- [ ] **Step 4: Run the full test suite as a final regression check**

Run: `uv run pytest -v`
Expected: all tests pass. Approximate count: 9 tests (settings ×2, healthz ×1, static ×3, home ×2, no-hardcoded-styles ×2 → some overlap; whatever the actual count is, all green).

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: local dev + deployment instructions for slice 1"
```

- [ ] **Step 6: Push the branch and open a PR**

```bash
git push -u origin slice1-scaffold
gh pr create --title "Slice 1: project scaffold" --body "$(cat <<'EOF'
## Summary
- FastAPI + Jinja + HTMX skeleton wired to AbstractNucleus/design tokens.
- Healthcheck, home page with empty-state card, /static asset mount.
- Dockerfile + docker-compose + Caddyfile for tailnet TLS deployment.
- Test suite: settings, healthz, static, home, no-hardcoded-styles.

## Test plan
- [ ] `uv run pytest -v` is green.
- [ ] `uv run ruff check .` is green.
- [ ] Visiting `/` in a browser shows the design system applied (warm paper, rust accent on focus, monospaced).
- [ ] `docker compose build` succeeds.
- [ ] First deploy on bserver issues a Let's Encrypt cert via Cloudflare DNS-01 (verified post-merge, not in CI).

Refs: docs/decisions.md (016, 002, 003); docs/patterns/tailnet-https-via-cloudflare.md.
EOF
)"
```

---

## Subsequent slice stubs

Each stub names the goal and the files added. A full plan for the next slice is written when its predecessor lands.

### Slice 2 — Supabase migration for `app_mcontrol` schema (lives in `supabase-server` repo)

Create `supabase/migrations/<timestamp>_create_app_mcontrol.sql` in the `supabase-server` repo on bserver. Tables:

- `app_mcontrol.servers` — `id` (uuid), `name` (text unique), `dir` (text — full path on host), `image_base` (text — e.g. `eclipse-temurin:21-jre`), `state` (text — last-seen container state), `variables` (jsonb — schema per decision 013), `rcon_password` (text), `created_at`, `updated_at`.

RLS off (decision 011 — `SERVICE_ROLE_KEY` server-side only). Run via `make migrate` on bserver. Add `app_mcontrol` to `PGRST_DB_SCHEMAS` if REST exposure is wanted (slice 1 doesn't need REST — server-side `service_role` calls bypass PGRST schema config anyway).

### Slice 3 — Server discovery + read-only server list

Walk `SERVER_BASE_PATH` (decision 008), match against `app_mcontrol.servers`, register new directories. Render the server list on `/` replacing the empty state. Adds `src/mcontrol/db.py` (Supabase client with service-role key), `src/mcontrol/docker_client.py` (aiodocker thin wrapper for container state lookup), `src/mcontrol/routes/server.py` (per-server detail page).

### Slice 4 — Lifecycle + log SSE + RCON console

Start/Stop/Restart buttons on the server detail page (HTMX-driven). SSE endpoint streaming `docker logs --follow`. SSE endpoint streaming RCON output, plus a POST endpoint for command submission. Adds `routes/lifecycle.py`, `routes/logs.py`, `routes/console.py`, `rcon.py`. Decision 010 governs the RCON-password write to `.env` on the host.

### Slice 5 — File browser + editor + uploads

Tree view of `<server>/server/`, browser-side editing via Monaco from CDN, single-file upload (server jar) and multi-file upload (mods). Path-traversal guards in `filesystem.py` are critical here — every path must be normalised and asserted to live under `SERVER_BASE_PATH`. Adds `routes/files.py`, `filesystem.py`.

### Slice 6 — New-server scaffolding flow

Form → generated `docker-compose.yml`, `Dockerfile`, `entrypoint.sh`, `start_server.sh`, `.env` (decisions 001, 008, 010, 012, 013). Adds `templates_gen.py`, `routes/new_server.py`, server-template j2 files.

### Slice 7 — Whitelist + ops UI

Per decision 018: RCON when running, file edits when offline, file edit + reload for granular op levels. Adds `routes/whitelist_ops.py`.

### Slice 8 — itzg → temurin migration for `atm10` + `monifactory`

One-time UI button (or CLI subcommand) per decision 014: rewrite Dockerfile base to `eclipse-temurin:21-jre`, rebuild image. World data untouched. `kobra_kollektivet` is unaffected.

---

## Self-review

Spec coverage: every decision register entry that this slice acts on (016, 002, 003) is implemented. Decisions deferred to later slices are deferred explicitly, not silently. Every step has concrete code or a concrete command — no placeholders. Type names are consistent: `Settings` (not `Config`), `create_app` (not `make_app`), `app.css` and `tokens.css` referenced identically across templates and tests. The hardcoded-style guard (Task 7) prevents future drift away from the design tokens, which is the discipline cost called out in decision 002.

Karpathy guidelines applied: settings has no speculative fields beyond what's needed in slices 1–4 (Supabase URL, service-role key, server base path are needed soon). The app factory has no plugin system, no middleware stack, no error-handling layer — only the routes the slice ships. The CSS guard fails loudly if anyone introduces a magic number.
