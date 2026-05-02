# mcontrol v1 — Slice 4: Lifecycle + Log SSE + RCON Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/servers/{name}` actually controllable — HTMX-driven Start/Stop/Restart, an SSE-streamed `docker logs` pane, and an RCON console (SSE for output + POST for command submission) — backed by lazy RCON-password generation that writes `<dir>/.env` on the host. Add a small inline "Bindings" card so the operator can repoint a row's docker container name and on-disk directory without re-running discovery.

**Architecture:** Five new modules sit alongside the slice-3 ones: `templates.py` (single shared `Jinja2Templates` extracted from slice-3 follow-up), `passwords.py` + `env_writer.py` + `compose_runner.py` (small operational helpers), `rcon.py` (bespoke ~80-line async Source RCON client). `docker_client.py` is extended with start/stop/restart/logs_stream/find_network. Four new route modules — `routes/lifecycle.py`, `routes/logs.py`, `routes/console.py`, `routes/bindings.py` — and the existing `routes/server.py` is widened so the detail page hosts the new affordances. The lifecycle path shells out to `docker compose -f <dir>/docker-compose.yml up -d --force-recreate` when `.env` changes, and uses aiodocker for cheap stop/restart. The RCON console attaches mcontrol's container to the MC container's docker network for the lifetime of the SSE stream and detaches on disconnect. All UI continues to consume only `tokens.css` variables; `tests/test_no_hardcoded_styles.py` continues to gate against drift.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, HTMX (existing); no new Python deps. Docker CLI + compose v2 plugin added to the runtime image (~50 MB). RCON written from scratch against the [Source RCON protocol](https://wiki.vg/RCON). Tests use `pytest`/`pytest-asyncio`/`httpx`/`monkeypatch`/`asyncio.start_server` fakes — no live Docker, no live Supabase in CI.

---

## Scope of this plan

This plan delivers **Slice 4 of v1 only**. Subsequent slices each get their own plan, written after the previous one lands:

| Slice | Scope | Plan |
|---|---|---|
| 5 | File browser + editor + jar/mod uploads | TBD |
| 6 | New-server scaffolding flow | TBD |
| 7 | Whitelist + ops UI | TBD |
| 8 | itzg → temurin migration for `atm10` + `monifactory` | TBD |

This split honours the writing-plans rule that each plan should produce working, testable software on its own. The Bindings UI is included **here** rather than alongside slice 5 because the underlying schema and discovery contract (decision 021) are introduced this slice — shipping the read/edit affordance now keeps the contract honest.

## Decisions register references

This slice acts on:

- **006** Direct `/var/run/docker.sock` mount — widens to `:rw`
- **008** Bind mounts at `~abstract/servers/minecraft/<name>/` — widens `SERVER_BASE_PATH` to `:rw`
- **010** RCON secrets in DB; mcontrol writes `.env`
- **011** `SERVICE_ROLE_KEY` server-side
- **013** Bespoke variable schema in `servers.variables` JSONB (unchanged this slice)
- **016** Backend stack: FastAPI + Jinja + HTMX (HTMX gets its first real workout)
- **020** Pin Docker image references (the new Docker CLI + compose plugin pins are added per this policy)

This slice introduces:

- **021** Per-server `container_name` override + discovery preserves operator edits (added in Task 14)

Deferred to later slices: 012, 014, 015, 017, 018.

## Spec reference

Source spec: `docs/superpowers/specs/2026-04-29-mcontrol-v1-slice4-design.md`. Read it before implementing if any task feels under-specified — the spec captures the design rationale (e.g. "why bespoke RCON, not `mcrcon`"). The plan below is the operational unfolding.

## Assumptions (surfaced, not buried)

1. **Slice 2's migration extension has landed on bserver before any task in this plan runs.** Pre-flight P2 (which the controller executes manually) writes the new `app_mcontrol.servers.container_name` column. Without it, the bindings code in Task 4/12 will return `column "container_name" does not exist`. The migration is small, idempotent, and additive — it does not affect existing reads (every consumer falls back to `name` when `container_name` is null).
2. **Each MC container's RCON server binds `0.0.0.0:25575` inside the container.** This is Minecraft's default when RCON is enabled in `server.properties`. Decision 010's "loopback by default" comment refers to host-port mapping (we don't expose RCON to the host), not the in-container bind interface. This is verified by inspection on bserver before slice-4 deploy.
3. **Each MC container is on a docker network reachable from mcontrol after `network.connect`.** The default per-server compose creates a single bridge network per project. mcontrol's container can be added to that network at runtime via the Docker API, with no compose-file edits.
4. **`HOSTNAME` env var inside mcontrol's container is the short container ID.** Docker sets this by default when `hostname:` is not specified in compose. We rely on it to know who-am-I when calling `network.connect(self_id)`. If this ever changes, fall back to reading `/etc/hostname`.
5. **`docker compose` (v2 plugin) is callable as `docker compose ...` inside the mcontrol container after Task 1 lands.** Not `docker-compose` (v1, hyphenated). The Dockerfile installs the official compose plugin from Docker's apt repo.
6. **Per-server compose files live at `<dir>/docker-compose.yml`** (where `<dir>` is the row's `dir` column). This matches existing bserver convention and is what slice 6 will generate. If a row's compose file is missing, lifecycle calls that need it (Start/Restart with stale `.env`) will surface the error; aiodocker-only paths (Stop, Restart-of-running-with-current-env) still work.
7. **Tests do not run live Docker or live Supabase.** Every test mocks at the boundary. The supabase-py module's `_client_singleton` reset pattern from slice 3 continues. aiodocker is mocked at `aiodocker.Docker` / `docker_client.aiodocker.Docker`. `asyncio.create_subprocess_exec` is mocked for `compose_runner` tests.
8. **The Docker CLI image bloat is acceptable.** Decision-level: the alternative (parsing per-server compose files ourselves) is worse than ~50 MB.
9. **Network attach is reversible per-stream.** When the RCON SSE disconnects, the `finally` clause detaches mcontrol from the MC's network. Worst case (process crash) leaves a stale attachment that's harmless until the next mcontrol restart, which doesn't auto-detach but the next attach idempotently reuses the connection.

## File structure for v1 (slice 4 touches files marked **§4**)

```
mcontrol/
├── pyproject.toml                              (existing)
├── Dockerfile                                  §4 (modify: docker CLI + compose plugin)
├── docker-compose.yml                          §4 (modify: :rw mounts)
├── docs/
│   ├── decisions.md                            §4 (modify: add entry 021)
│   ├── plans/
│   │   └── 2026-04-29-mcontrol-v1-slice4-...md (this file)
│   └── superpowers/specs/
│       └── 2026-04-29-mcontrol-v1-slice4-design.md (existing)
├── src/
│   └── mcontrol/
│       ├── main.py                             §4 (modify: register new routers, attach templates to app.state)
│       ├── templates.py                        §4 (new — shared Jinja2Templates)
│       ├── db.py                               §4 (modify: insert/update split, bindings, password setter, container_name lookup)
│       ├── discovery.py                        §4 (modify: preserve operator edits)
│       ├── docker_client.py                    §4 (modify: drop N+1, add start/stop/restart/logs_stream/find_network/self_id)
│       ├── rcon.py                             §4 (new — bespoke async RCON client)
│       ├── passwords.py                        §4 (new — token generation)
│       ├── env_writer.py                       §4 (new — atomic .env writer/reader)
│       ├── compose_runner.py                   §4 (new — async wrapper over `docker compose`)
│       ├── routes/
│       │   ├── home.py                         §4 (modify: use shared templates)
│       │   ├── server.py                       §4 (modify: use shared templates, pass new context)
│       │   ├── lifecycle.py                    §4 (new)
│       │   ├── logs.py                         §4 (new)
│       │   ├── console.py                      §4 (new)
│       │   └── bindings.py                     §4 (new)
│       ├── templates/
│       │   ├── server_detail.html              §4 (modify: add buttons + panes + bindings card)
│       │   ├── _state_pill.html                §4 (new — partial returned by lifecycle POSTs)
│       │   ├── _log_pane.html                  §4 (new — log SSE pane)
│       │   ├── _console_pane.html              §4 (new — RCON SSE pane + form)
│       │   ├── _bindings_card.html             §4 (new — read-only bindings)
│       │   └── _bindings_form.html             §4 (new — bindings edit form)
│       └── static/
│           └── app.css                         §4 (modify: layout for buttons/panes/bindings — token-only)
└── tests/
    ├── conftest.py                             §4 (modify: shared fakes for new modules where useful)
    ├── test_db.py                              §4 (modify: tests for new db helpers)
    ├── test_discovery.py                       §4 (modify: preserve-edits behaviour)
    ├── test_docker_client.py                   §4 (modify: N+1 fix, inner-branch failure, new methods)
    ├── test_passwords.py                       §4 (new)
    ├── test_env_writer.py                      §4 (new)
    ├── test_compose_runner.py                  §4 (new)
    ├── test_rcon.py                            §4 (new)
    ├── test_lifecycle.py                       §4 (new)
    ├── test_logs.py                            §4 (new)
    ├── test_console.py                         §4 (new)
    ├── test_bindings.py                        §4 (new)
    ├── test_server_detail.py                   §4 (modify: assert new affordances render)
    ├── test_templates_module.py                §4 (new — verifies the shared Jinja2Templates is used)
    └── test_no_hardcoded_styles.py             (existing — must stay green)
```

External (controller-managed, not in this repo):
- `supabase-server/supabase/migrations/<timestamp>_app_mcontrol_container_name.sql` — applied via `make migrate` on bserver during pre-flight (P2).

---

# Pre-flight

- [ ] **P1: Confirm we are on the slice-4 branch and clean**

```bash
git checkout slice4-lifecycle-logs-rcon
git status
git log --oneline 2d899ef..HEAD
```

Expected:
- on `slice4-lifecycle-logs-rcon`
- working tree clean
- one commit, the slice-4 design spec (`94ac894 docs(spec): slice-4 design — lifecycle + log SSE + RCON console`)

If the spec commit is missing, stop and investigate — the spec must be on this branch.

- [ ] **P2: Apply the `app_mcontrol.servers.container_name` migration on bserver**

This step is the **controller's** job — the implementer subagent never touches bserver. The controller SSHes in, writes the migration file, runs `make migrate`, commits and pushes the supabase-server repo.

```bash
ssh bserver
cd ~/repos/supabase-server
git pull --ff-only
TS=$(date +%Y%m%d%H%M%S)
cat > supabase/migrations/${TS}_app_mcontrol_container_name.sql <<'SQL'
-- mcontrol slice 4 — per-server container_name override.
-- Nullable; falls back to `name` when null. No backfill needed.

alter table app_mcontrol.servers
    add column if not exists container_name text;
SQL
make migrate
git add supabase/migrations/${TS}_app_mcontrol_container_name.sql
git commit -m "feat(app_mcontrol): add servers.container_name override column

Slice 4 of mcontrol introduces per-row container-name override so the
docker container a row points at can drift from the row's directory
name. Column is nullable; readers fall back to \`name\` when null."
git push
```

Verify via PostgREST:

```bash
curl -fsS \
  -H "apikey: $SR_KEY" \
  -H "Authorization: Bearer $SR_KEY" \
  -H "Accept-Profile: app_mcontrol" \
  'https://api.noelkleen.com/rest/v1/servers?select=name,container_name&limit=1'
```

Expected: rows include a `container_name` field (likely null for existing rows). If the response says `column "container_name" does not exist`, the migration did not apply — investigate before continuing.

- [ ] **P3: Confirm the slice-3 baseline tests pass on the slice-4 branch**

```bash
uv run pytest -v
uv run ruff check .
```

Expected: 36 passed, ruff clean. (The slice-4 branch starts at `2d899ef + spec commit`, which has no code changes from slice 3.)

- [ ] **P4: Confirm `uv` is installed and the venv resolves**

```bash
uv --version
uv sync
```

Expected: a `uv 0.x` version string and `Resolved N packages` exit-0.

---

# Task 1: Operational baseline — Dockerfile + compose mount changes

**Why first.** Every later task assumes `:rw` mounts and the `docker compose` CLI being available inside the container at deploy. Doing this first means the deploy shape is locked before any code reads from it.

**Files:**
- Modify: `Dockerfile`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Patch `Dockerfile` to install Docker CLI + compose plugin (pinned)**

Read the current `Dockerfile` first. Then replace the `RUN uv sync --frozen --no-dev --no-install-project` block with one that, ahead of the uv install, also installs Docker's CLI and compose plugin from the official apt repo.

The replacement block to insert after `WORKDIR /app` and before `COPY pyproject.toml uv.lock ./`:

```dockerfile
# Docker CLI + compose v2 plugin, used by mcontrol to recreate per-server
# containers when the .env (RCON_PASSWORD) changes. Pinned per decision 020.
ARG DOCKER_CE_CLI_VERSION=5:27.4.0-1~debian.12~bookworm
ARG DOCKER_COMPOSE_PLUGIN_VERSION=2.31.0-1~debian.12~bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && chmod a+r /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian bookworm stable" \
        > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        "docker-ce-cli=${DOCKER_CE_CLI_VERSION}" \
        "docker-compose-plugin=${DOCKER_COMPOSE_PLUGIN_VERSION}" \
    && rm -rf /var/lib/apt/lists/*
```

(Pins are explicit per decision 020. If apt resolution at build time complains those exact versions are no longer in the channel, bump to the closest current patch and update this plan in a follow-up commit.)

- [ ] **Step 2: Verify the Dockerfile builds locally (or skip on Windows dev)**

On Linux/macOS with Docker available:

```bash
docker compose build app
```

Expected: the build succeeds. The new layer is large (~50 MB) — that's expected.

On Windows dev where `docker compose` may not be available without WSL2: skip this verification and rely on the bserver deploy smoke (Task 15) to catch any Dockerfile breakage.

- [ ] **Step 3: Patch `docker-compose.yml` mounts to `:rw`**

Read the current file. Replace the two `:ro` suffixes with `:rw`. Final mounts block under the `app` service:

```yaml
    volumes:
      # Slice 4: rw so we can `docker start/stop/exec`, attach networks,
      # and `docker compose up -d --force-recreate` from inside the panel.
      - /var/run/docker.sock:/var/run/docker.sock:rw
      # Slice 4: rw so we can write <dir>/.env (RCON_PASSWORD) per decision 010.
      - ${SERVER_BASE_PATH}:${SERVER_BASE_PATH}:rw
```

- [ ] **Step 4: Re-run tests**

```bash
uv run pytest -v
```

Expected: 36 passed (no test asserts mount mode; this step just confirms nothing collateral broke).

- [ ] **Step 5: Commit**

```bash
git add Dockerfile docker-compose.yml
git commit -m "chore(deploy): docker CLI + :rw mounts for slice 4

Adds Docker CLI + compose v2 plugin (pinned) to the runtime image so
mcontrol can shell out to \`docker compose -f <dir>/docker-compose.yml
up -d --force-recreate\` when an MC container's .env changes. Widens
SERVER_BASE_PATH and /var/run/docker.sock mounts to :rw — the panel
needs to write .env files and start/stop/exec containers."
```

---

# Task 2: Slice-3 follow-ups (templates module, drop N+1, inner-branch test)

**Why second.** Three small cleanups land before the new feature surface area — they reduce churn in later tasks (every new route would otherwise create its own `Jinja2Templates`) and close documented coverage gaps.

**Files:**
- Create: `src/mcontrol/templates.py`
- Modify: `src/mcontrol/main.py`
- Modify: `src/mcontrol/routes/home.py`
- Modify: `src/mcontrol/routes/server.py`
- Modify: `src/mcontrol/docker_client.py`
- Modify: `tests/test_docker_client.py`
- Create: `tests/test_templates_module.py`

- [ ] **Step 1: Write the failing test for the shared templates module**

Create `tests/test_templates_module.py`:

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_templates_module.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mcontrol.templates'`.

- [ ] **Step 3: Create the shared templates module**

Create `src/mcontrol/templates.py`:

```python
"""Shared Jinja2Templates instance for all mcontrol routes.

Slice 3 inlined `Jinja2Templates(directory=TEMPLATES_DIR)` in both
routes/home.py and routes/server.py. Slice 4 adds four more route
modules; sharing a single instance keeps configuration in one place.
"""

from pathlib import Path

from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)
```

- [ ] **Step 4: Update `routes/home.py` to consume the shared instance**

Replace `src/mcontrol/routes/home.py` with:

```python
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from mcontrol import __version__, db
from mcontrol.templates import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    servers = db.list_servers()
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"version": __version__, "servers": servers},
    )
```

- [ ] **Step 5: Update `routes/server.py` to consume the shared instance**

Replace `src/mcontrol/routes/server.py` with:

```python
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from mcontrol import __version__, db
from mcontrol.templates import templates

router = APIRouter()


@router.get("/servers/{name}", response_class=HTMLResponse)
async def server_detail(request: Request, name: str) -> HTMLResponse:
    server = db.get_server(name)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")
    return templates.TemplateResponse(
        request=request,
        name="server_detail.html",
        context={"version": __version__, "server": server},
    )
```

- [ ] **Step 6: Run the new test + re-run the existing suite**

```bash
uv run pytest tests/test_templates_module.py -v
uv run pytest -v
```

Expected: 38 passed (36 existing + 2 new). No regression.

- [ ] **Step 7: Drop the N+1 in `docker_client.container_states_by_name`**

Read the current `src/mcontrol/docker_client.py`. The current implementation calls `await c.show()` for each container — `containers.list()` already returns summary objects with `Status` and `Names` populated. Replace the function body:

```python
"""Thin async wrapper around aiodocker for container-state lookups.

Slice 3 only needed to enumerate container names + statuses. Slice 4 will
extend this module with start/stop/logs operations.
"""

from contextlib import suppress

import aiodocker

from mcontrol.settings import Settings


async def container_states_by_name() -> dict[str, str]:
    """Return {container_name: status} for every container on the host.

    Returns an empty dict if the Docker daemon is unreachable — callers
    treat "no entry" as state="unknown" for that server.
    """
    settings = Settings()
    try:
        docker = aiodocker.Docker(url=settings.docker_host)
    except Exception:
        return {}

    try:
        containers = await docker.containers.list(all=True)
        states: dict[str, str] = {}
        for c in containers:
            # Each container summary has _container (the raw dict from /containers/json).
            # 'Names' is a list of names with leading slash; pick the first.
            raw = c._container if hasattr(c, "_container") else {}
            names = raw.get("Names") or []
            if not names:
                continue
            name = names[0].lstrip("/")
            status = raw.get("State") or raw.get("Status", "unknown")
            states[name] = status
        return states
    except Exception:
        return {}
    finally:
        with suppress(Exception):
            await docker.close()
```

(`aiodocker.DockerContainer._container` is a public-shape dict in 0.24+. If it isn't present in your installed version, fall back to `c.show()` once per container — surface the version mismatch in the implementer's report.)

- [ ] **Step 8: Update `tests/test_docker_client.py` to match the new shape + add the inner-branch test**

The slice-3 fakes built `_FakeContainer` around `show()`. Update the fakes so the summary objects expose `._container` directly. Replace the file with:

```python
from unittest.mock import AsyncMock, MagicMock

import pytest

from mcontrol import docker_client


class _FakeSummary:
    """Mimics aiodocker.DockerContainer with a populated `_container` dict
    (the /containers/json summary), which is what container_states_by_name
    now reads."""

    def __init__(self, name: str, status: str):
        self._container = {"Names": [f"/{name}"], "State": status}


class _FakeContainers:
    def __init__(self, containers: list[_FakeSummary]):
        self._containers = containers

    async def list(self, all: bool = False) -> list[_FakeSummary]:  # noqa: A002
        assert all is True, "discovery must list ALL containers, including stopped"
        return self._containers


class _FakeDocker:
    def __init__(self, containers: list[_FakeSummary]):
        self.containers = _FakeContainers(containers)
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_docker(monkeypatch):
    containers: list[_FakeSummary] = []

    def factory(*, url: str | None = None) -> _FakeDocker:
        return _FakeDocker(containers)

    monkeypatch.setattr(docker_client.aiodocker, "Docker", factory)
    return containers


async def test_container_states_by_name_returns_mapping(env, fake_docker):
    fake_docker.append(_FakeSummary("atm10", "running"))
    fake_docker.append(_FakeSummary("monifactory", "exited"))

    states = await docker_client.container_states_by_name()

    assert states == {"atm10": "running", "monifactory": "exited"}


async def test_container_states_strips_leading_slash(env, fake_docker):
    fake_docker.append(_FakeSummary("kobra_kollektivet", "created"))

    states = await docker_client.container_states_by_name()

    assert states == {"kobra_kollektivet": "created"}


async def test_container_states_returns_empty_when_docker_constructor_fails(env, monkeypatch):
    class _Boom:
        def __init__(self, *_, **__):
            raise RuntimeError("docker daemon is sulking")

    monkeypatch.setattr(docker_client.aiodocker, "Docker", _Boom)

    states = await docker_client.container_states_by_name()

    assert states == {}


async def test_container_states_returns_empty_when_list_raises(env, monkeypatch):
    """Inner-branch failure: constructor succeeds but containers.list raises."""

    class _PartiallyBrokenDocker:
        def __init__(self, *_, **__):
            self.containers = MagicMock()
            self.containers.list = AsyncMock(side_effect=RuntimeError("kernel said no"))

        async def close(self):
            pass

    monkeypatch.setattr(docker_client.aiodocker, "Docker", _PartiallyBrokenDocker)

    states = await docker_client.container_states_by_name()

    assert states == {}


async def test_container_states_closes_the_client(env, monkeypatch):
    closed_flag = {"closed": False}

    class _TrackingDocker:
        def __init__(self, *_, **__):
            self.containers = MagicMock()
            self.containers.list = AsyncMock(return_value=[])

        async def close(self):
            closed_flag["closed"] = True

    monkeypatch.setattr(docker_client.aiodocker, "Docker", _TrackingDocker)

    await docker_client.container_states_by_name()

    assert closed_flag["closed"] is True
```

- [ ] **Step 9: Run the docker_client tests + the full suite**

```bash
uv run pytest tests/test_docker_client.py -v
uv run pytest -v
```

Expected: 5 tests in `test_docker_client.py` pass (was 4); full suite green.

- [ ] **Step 10: Commit**

```bash
git add src/mcontrol/templates.py \
        src/mcontrol/routes/home.py \
        src/mcontrol/routes/server.py \
        src/mcontrol/docker_client.py \
        tests/test_docker_client.py \
        tests/test_templates_module.py
git commit -m "refactor(slice3-followups): shared templates, drop docker N+1, inner-branch test

Three slice-3 final-review follow-ups, folded into slice 4 since slice
4 adds four more route modules that would otherwise duplicate the
Jinja2Templates instance:

  - Extract mcontrol.templates as the single Jinja2Templates instance.
  - docker_client.container_states_by_name reads State/Names directly
    from the container summary (already returned by containers.list);
    drops the per-container show() round trip.
  - New test for the inner-branch failure path: docker constructor
    succeeds but .list() raises; we return {} and don't propagate."
```

---

# Task 3: `db.py` extensions — bindings + state-only update + lazy password

**Files:**
- Modify: `src/mcontrol/db.py`
- Modify: `tests/test_db.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db.py` (keep the existing tests as-is; the existing `_reset_client_singleton` autouse fixture covers all tests):

```python
def test_insert_server_writes_full_row(env, monkeypatch):
    client, table = _fake_supabase_client()
    monkeypatch.setattr(db, "_client_singleton", client)

    db.insert_server(name="atm10", dir="/srv/atm10", state="unknown")

    table.insert.assert_called_once_with(
        {"name": "atm10", "dir": "/srv/atm10", "state": "unknown"}
    )
    table.insert.return_value.execute.assert_called_once_with()


def test_update_server_state_writes_only_state(env, monkeypatch):
    client, table = _fake_supabase_client()
    monkeypatch.setattr(db, "_client_singleton", client)

    db.update_server_state(name="atm10", state="running")

    args, kwargs = table.update.call_args
    assert args == ({"state": "running"},)
    table.update.return_value.eq.assert_called_once_with("name", "atm10")


def test_update_bindings_writes_container_name_and_dir(env, monkeypatch):
    client, table = _fake_supabase_client()
    monkeypatch.setattr(db, "_client_singleton", client)

    db.update_bindings(name="atm10", container_name="atm10-prod", dir="/srv/atm10")

    args, kwargs = table.update.call_args
    assert args == ({"container_name": "atm10-prod", "dir": "/srv/atm10"},)
    table.update.return_value.eq.assert_called_once_with("name", "atm10")


def test_set_rcon_password_updates_password_only(env, monkeypatch):
    client, table = _fake_supabase_client()
    monkeypatch.setattr(db, "_client_singleton", client)

    db.set_rcon_password(name="atm10", password="hunter2")

    args, kwargs = table.update.call_args
    assert args == ({"rcon_password": "hunter2"},)
    table.update.return_value.eq.assert_called_once_with("name", "atm10")


def test_container_name_for_falls_back_to_name_when_override_null():
    row = {"name": "atm10", "container_name": None}
    assert db.container_name_for(row) == "atm10"


def test_container_name_for_uses_override_when_present():
    row = {"name": "atm10", "container_name": "atm10-prod"}
    assert db.container_name_for(row) == "atm10-prod"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_db.py -v`
Expected: 6 new tests FAIL with `AttributeError: module 'mcontrol.db' has no attribute 'insert_server'` (etc.).

- [ ] **Step 3: Extend `src/mcontrol/db.py`**

Replace the file with:

```python
"""Thin wrapper over supabase-py, scoped to app_mcontrol.servers.

All callers go through the helpers below. The underlying client is
constructed lazily on first use and cached for the lifetime of the
process.
"""

from typing import Any

from supabase import Client, create_client

from mcontrol.settings import Settings

_SCHEMA = "app_mcontrol"
_TABLE = "servers"

_client_singleton: Client | None = None


def _client() -> Client:
    global _client_singleton
    if _client_singleton is None:
        settings = Settings()
        _client_singleton = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key,
        )
    return _client_singleton


def _table():
    return _client().schema(_SCHEMA).table(_TABLE)


def list_servers() -> list[dict[str, Any]]:
    response = _table().select("*").order("name").execute()
    return response.data


def get_server(name: str) -> dict[str, Any] | None:
    response = _table().select("*").eq("name", name).limit(1).execute()
    return response.data[0] if response.data else None


def insert_server(*, name: str, dir: str, state: str) -> None:
    """Create a new row. Used by discovery on first encounter only —
    subsequent scans use update_server_state so operator edits to dir
    and container_name survive."""
    _table().insert({"name": name, "dir": dir, "state": state}).execute()


def update_server_state(*, name: str, state: str) -> None:
    """Refresh a row's state. Does NOT touch dir or container_name."""
    _table().update({"state": state}).eq("name", name).execute()


def update_bindings(*, name: str, container_name: str | None, dir: str) -> None:
    """Operator-driven update of the row's container-name override and
    on-disk directory. `container_name=None` clears the override (back
    to falling back to `name`)."""
    _table().update(
        {"container_name": container_name, "dir": dir}
    ).eq("name", name).execute()


def set_rcon_password(*, name: str, password: str) -> None:
    _table().update({"rcon_password": password}).eq("name", name).execute()


def container_name_for(server: dict[str, Any]) -> str:
    """Resolve the docker container name for a server row.

    Returns the explicit container_name override when set, otherwise
    falls back to the row's `name`. Decision 021.
    """
    override = server.get("container_name")
    if override:
        return override
    return server["name"]


# upsert_server stays as-is for any external caller; discovery no
# longer uses it. Slice 4 leaves the function in place so test_db's
# slice-3 upsert tests continue to pass without modification.
def upsert_server(*, name: str, dir: str, state: str) -> None:
    _table().upsert(
        {"name": name, "dir": dir, "state": state},
        on_conflict="name",
    ).execute()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_db.py -v`
Expected: 13 passed (7 existing + 6 new).

- [ ] **Step 5: Run the full suite**

```bash
uv run pytest -v
```

Expected: full green.

- [ ] **Step 6: Commit**

```bash
git add src/mcontrol/db.py tests/test_db.py
git commit -m "feat(db): bindings + state-only update + lazy password setter

Adds insert_server, update_server_state, update_bindings,
set_rcon_password, and container_name_for(row) — the lookup helper
that returns the operator override when set and falls back to
servers.name otherwise (decision 021). upsert_server stays for
backward compatibility but discovery moves to insert/update split
in the next task."
```

---

# Task 4: Discovery preserves operator edits

**Files:**
- Modify: `src/mcontrol/discovery.py`
- Modify: `tests/test_discovery.py`

- [ ] **Step 1: Update the failing tests**

Replace `tests/test_discovery.py` with:

```python
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from mcontrol import discovery


@pytest.fixture
def db_calls(monkeypatch):
    """Capture every db call discovery makes — order matters for the assertions."""
    calls: list[tuple[str, dict]] = []

    def fake_get_server(name):
        # Default: row does not exist. Tests override per-name by setting
        # discovery._existing_rows on the fixture before calling.
        return _existing_rows.get(name)

    def fake_insert_server(**kwargs):
        calls.append(("insert", kwargs))

    def fake_update_server_state(**kwargs):
        calls.append(("update_state", kwargs))

    _existing_rows: dict[str, dict | None] = {}

    monkeypatch.setattr(discovery.db, "get_server", fake_get_server)
    monkeypatch.setattr(discovery.db, "insert_server", fake_insert_server)
    monkeypatch.setattr(discovery.db, "update_server_state", fake_update_server_state)

    return {"calls": calls, "existing": _existing_rows}


def _make_dirs(base: Path, names: list[str]) -> None:
    for n in names:
        (base / n).mkdir(parents=True, exist_ok=True)


async def test_run_discovery_skips_when_base_path_missing(tmp_path, db_calls, monkeypatch):
    monkeypatch.setattr(
        discovery.docker_client,
        "container_states_by_name",
        AsyncMock(return_value={}),
    )

    count = await discovery.run_discovery(tmp_path / "does-not-exist")

    assert count == 0
    assert db_calls["calls"] == []


async def test_run_discovery_inserts_new_dirs(tmp_path, db_calls, monkeypatch):
    _make_dirs(tmp_path, ["atm10", "monifactory"])
    monkeypatch.setattr(
        discovery.docker_client,
        "container_states_by_name",
        AsyncMock(return_value={"atm10": "running"}),
    )

    count = await discovery.run_discovery(tmp_path)

    assert count == 2
    inserts = [c for c in db_calls["calls"] if c[0] == "insert"]
    updates = [c for c in db_calls["calls"] if c[0] == "update_state"]
    assert {i[1]["name"] for i in inserts} == {"atm10", "monifactory"}
    assert updates == []
    assert next(i for i in inserts if i[1]["name"] == "atm10")[1] == {
        "name": "atm10",
        "dir": str(tmp_path / "atm10"),
        "state": "running",
    }


async def test_run_discovery_updates_state_only_for_existing_rows(tmp_path, db_calls, monkeypatch):
    _make_dirs(tmp_path, ["atm10"])
    db_calls["existing"]["atm10"] = {
        "name": "atm10",
        "dir": "/operator/edited/path/atm10",
        "container_name": "atm10-prod",
        "state": "exited",
    }
    monkeypatch.setattr(
        discovery.docker_client,
        "container_states_by_name",
        AsyncMock(return_value={"atm10": "running"}),
    )

    count = await discovery.run_discovery(tmp_path)

    assert count == 1
    inserts = [c for c in db_calls["calls"] if c[0] == "insert"]
    updates = [c for c in db_calls["calls"] if c[0] == "update_state"]
    # No insert — operator-edited row is preserved.
    assert inserts == []
    # Only state is refreshed; dir and container_name untouched.
    assert updates == [("update_state", {"name": "atm10", "state": "running"})]


async def test_run_discovery_falls_back_to_unknown_when_docker_silent(tmp_path, db_calls, monkeypatch):
    _make_dirs(tmp_path, ["atm10"])
    monkeypatch.setattr(
        discovery.docker_client,
        "container_states_by_name",
        AsyncMock(return_value={}),
    )

    count = await discovery.run_discovery(tmp_path)

    assert count == 1
    inserts = [c for c in db_calls["calls"] if c[0] == "insert"]
    assert inserts[0][1]["state"] == "unknown"


async def test_run_discovery_ignores_non_directories(tmp_path, db_calls, monkeypatch):
    _make_dirs(tmp_path, ["atm10"])
    (tmp_path / "stray-file.txt").write_text("ignore me")
    monkeypatch.setattr(
        discovery.docker_client,
        "container_states_by_name",
        AsyncMock(return_value={}),
    )

    count = await discovery.run_discovery(tmp_path)

    assert count == 1


async def test_run_discovery_processes_dirs_in_sorted_order(tmp_path, db_calls, monkeypatch):
    _make_dirs(tmp_path, ["zeta", "alpha", "mu"])
    monkeypatch.setattr(
        discovery.docker_client,
        "container_states_by_name",
        AsyncMock(return_value={}),
    )

    await discovery.run_discovery(tmp_path)

    seen = [c[1]["name"] for c in db_calls["calls"]]
    assert seen == ["alpha", "mu", "zeta"]


async def test_run_discovery_state_lookup_uses_container_name_override(tmp_path, db_calls, monkeypatch):
    """When a row has container_name override, state is looked up under that name."""
    _make_dirs(tmp_path, ["atm10"])
    db_calls["existing"]["atm10"] = {
        "name": "atm10",
        "container_name": "atm10-prod",
        "dir": str(tmp_path / "atm10"),
        "state": "exited",
    }
    monkeypatch.setattr(
        discovery.docker_client,
        "container_states_by_name",
        # The override "atm10-prod" is what's running; the row's name "atm10"
        # is not a real container.
        AsyncMock(return_value={"atm10-prod": "running"}),
    )

    await discovery.run_discovery(tmp_path)

    updates = [c for c in db_calls["calls"] if c[0] == "update_state"]
    assert updates == [("update_state", {"name": "atm10", "state": "running"})]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_discovery.py -v`
Expected: most tests fail because `discovery.run_discovery` still uses `db.upsert_server`.

- [ ] **Step 3: Update `discovery.py` to preserve operator edits**

Replace `src/mcontrol/discovery.py` with:

```python
"""Server discovery — walks SERVER_BASE_PATH and registers each
subdirectory in app_mcontrol.servers, refreshing its state from Docker.

Design (decision 021): this routine is idempotent and **non-destructive
of operator edits**. On a re-scan, dir and container_name (which the
operator may have edited) are NEVER overwritten — only `state` is
refreshed. New directories are inserted with default values; existing
rows are touched only on the `state` column.

Designed to run once on app startup via FastAPI's lifespan context
manager.
"""

from pathlib import Path

from mcontrol import db, docker_client


async def run_discovery(base_path: Path) -> int:
    """Walk base_path, insert new rows, refresh state on existing rows.

    Returns the count of dirs seen. If base_path doesn't exist, returns
    0 without touching the DB. If Docker is unreachable, every dir
    gets state="unknown" via the empty mapping returned from
    docker_client.
    """
    if not base_path.exists():
        return 0

    states = await docker_client.container_states_by_name()
    count = 0
    for entry in sorted(base_path.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue

        existing = db.get_server(entry.name)
        if existing is None:
            db.insert_server(
                name=entry.name,
                dir=str(entry),
                state=states.get(entry.name, "unknown"),
            )
        else:
            # Use the row's container_name override when looking up state —
            # the actual docker container may be named differently from the
            # directory once an operator has repointed it.
            container_name = db.container_name_for(existing)
            db.update_server_state(
                name=entry.name,
                state=states.get(container_name, "unknown"),
            )
        count += 1
    return count
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_discovery.py -v
uv run pytest -v
```

Expected: all discovery tests green; full suite green.

- [ ] **Step 5: Commit**

```bash
git add src/mcontrol/discovery.py tests/test_discovery.py
git commit -m "feat(discovery): preserve operator edits to dir + container_name

Slice 3's upsert clobbered dir on every scan, which would erase
operator overrides. Slice 4 splits into insert-on-new and
update-state-only-on-existing so dir and container_name survive
re-scans. State lookup respects the container_name override so a
re-pointed row shows the right state. Decision 021."
```

---

# Task 5: Foundation utilities — `passwords.py` + `env_writer.py`

**Files:**
- Create: `src/mcontrol/passwords.py`
- Create: `src/mcontrol/env_writer.py`
- Create: `tests/test_passwords.py`
- Create: `tests/test_env_writer.py`

- [ ] **Step 1: Write the failing tests for `passwords.py`**

Create `tests/test_passwords.py`:

```python
import re

from mcontrol import passwords


def test_generate_returns_url_safe_string():
    pwd = passwords.generate()
    # token_urlsafe(24) produces a 32-char string of [A-Za-z0-9_-].
    assert len(pwd) == 32
    assert re.fullmatch(r"[A-Za-z0-9_\-]+", pwd)


def test_generate_returns_distinct_values():
    pwds = {passwords.generate() for _ in range(20)}
    # Cryptographically-random; the chance of any collision in 20 pulls is negligible.
    assert len(pwds) == 20
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_passwords.py -v`
Expected: FAIL — `ModuleNotFoundError: mcontrol.passwords`.

- [ ] **Step 3: Implement `passwords.py`**

Create `src/mcontrol/passwords.py`:

```python
"""RCON password generation. Decision 010."""

import secrets


def generate() -> str:
    """Return a fresh URL-safe RCON password (~192 bits of entropy)."""
    return secrets.token_urlsafe(24)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_passwords.py -v`
Expected: 2 passed.

- [ ] **Step 5: Write the failing tests for `env_writer.py`**

Create `tests/test_env_writer.py`:

```python
from pathlib import Path

import pytest

from mcontrol import env_writer


def test_write_rcon_password_creates_env_when_absent(tmp_path):
    env_path = tmp_path / ".env"

    env_writer.write_rcon_password(env_path, "hunter2")

    assert env_path.read_text() == "RCON_PASSWORD=hunter2\n"


def test_write_rcon_password_overwrites_existing_line(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("OTHER=value\nRCON_PASSWORD=oldpwd\nKEEP_ME=yes\n")

    env_writer.write_rcon_password(env_path, "newpwd")

    text = env_path.read_text()
    assert "OTHER=value" in text
    assert "KEEP_ME=yes" in text
    assert "RCON_PASSWORD=newpwd" in text
    assert "RCON_PASSWORD=oldpwd" not in text


def test_write_rcon_password_appends_when_var_absent(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("OTHER=value\n")

    env_writer.write_rcon_password(env_path, "hunter2")

    text = env_path.read_text()
    assert text.endswith("RCON_PASSWORD=hunter2\n")
    assert "OTHER=value" in text


def test_write_rcon_password_creates_parent_directories(tmp_path):
    env_path = tmp_path / "deep" / "nested" / "dir" / ".env"

    env_writer.write_rcon_password(env_path, "hunter2")

    assert env_path.exists()


def test_write_rcon_password_uses_atomic_replace(tmp_path, monkeypatch):
    """Ensures the writer goes through a temp-file + os.replace dance,
    so a partial write can never leave a half-written .env."""
    env_path = tmp_path / ".env"
    env_path.write_text("RCON_PASSWORD=oldpwd\n")

    seen_paths: list[Path] = []
    real_replace = Path.replace

    def tracking_replace(self, target):
        seen_paths.append(self)
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", tracking_replace)

    env_writer.write_rcon_password(env_path, "newpwd")

    assert any(p != env_path for p in seen_paths), "writer should replace from a temp path"
    assert env_path.read_text() == "RCON_PASSWORD=newpwd\n"


def test_read_rcon_password_returns_none_when_file_absent(tmp_path):
    assert env_writer.read_rcon_password(tmp_path / "nope") is None


def test_read_rcon_password_returns_value_when_present(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("OTHER=value\nRCON_PASSWORD=hunter2\nKEEP=yes\n")

    assert env_writer.read_rcon_password(env_path) == "hunter2"


def test_read_rcon_password_returns_none_when_var_absent(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("OTHER=value\n")

    assert env_writer.read_rcon_password(env_path) is None
```

- [ ] **Step 6: Run to verify they fail**

Run: `uv run pytest tests/test_env_writer.py -v`
Expected: FAIL — `ModuleNotFoundError: mcontrol.env_writer`.

- [ ] **Step 7: Implement `env_writer.py`**

Create `src/mcontrol/env_writer.py`:

```python
"""Atomic writer for the `RCON_PASSWORD=...` line in <dir>/.env.

Per decision 010, mcontrol owns this file's RCON_PASSWORD entry. Other
keys (operator-managed) are preserved verbatim. The write goes through
a temp file + os.replace so a partial write can't leave a half-baked
.env on disk.
"""

import os
import tempfile
from pathlib import Path

_RCON_KEY = "RCON_PASSWORD"


def write_rcon_password(env_path: Path, password: str) -> None:
    """Set RCON_PASSWORD=<password> in env_path, preserving other lines.

    Creates env_path (and parent dirs) if absent.
    """
    env_path.parent.mkdir(parents=True, exist_ok=True)

    existing_lines: list[str] = []
    if env_path.exists():
        existing_lines = env_path.read_text().splitlines()

    new_lines: list[str] = []
    replaced = False
    for line in existing_lines:
        if line.startswith(f"{_RCON_KEY}="):
            new_lines.append(f"{_RCON_KEY}={password}")
            replaced = True
        else:
            new_lines.append(line)

    if not replaced:
        new_lines.append(f"{_RCON_KEY}={password}")

    body = "\n".join(new_lines) + "\n"

    # Atomic replace: write to a sibling temp file, then rename over.
    fd, tmp_str = tempfile.mkstemp(prefix=".env.", dir=str(env_path.parent))
    tmp_path = Path(tmp_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        tmp_path.replace(env_path)
    except Exception:
        # Best-effort cleanup of the temp file if the rename failed.
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def read_rcon_password(env_path: Path) -> str | None:
    """Return the current RCON_PASSWORD value, or None if not set."""
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        if line.startswith(f"{_RCON_KEY}="):
            return line.split("=", 1)[1]
    return None
```

- [ ] **Step 8: Run to verify they pass**

```bash
uv run pytest tests/test_passwords.py tests/test_env_writer.py -v
uv run pytest -v
```

Expected: 2 + 8 = 10 new tests pass; full suite green.

- [ ] **Step 9: Commit**

```bash
git add src/mcontrol/passwords.py src/mcontrol/env_writer.py \
        tests/test_passwords.py tests/test_env_writer.py
git commit -m "feat(slice4): passwords.generate + atomic env_writer for RCON_PASSWORD

Two small helpers used by the lifecycle path. passwords.generate
returns a URL-safe ~192-bit token via secrets.token_urlsafe(24).
env_writer.write_rcon_password sets the RCON_PASSWORD line in
<dir>/.env without touching other lines, going through a temp file
+ os.replace so a partial write never leaves a corrupt .env."
```

---

# Task 6: `compose_runner.py` — async wrapper over `docker compose`

**Files:**
- Create: `src/mcontrol/compose_runner.py`
- Create: `tests/test_compose_runner.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_compose_runner.py`:

```python
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from mcontrol import compose_runner


class _FakeProcess:
    def __init__(self, returncode: int, stderr: bytes = b""):
        self.returncode = returncode
        self._stderr = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        return (b"", self._stderr)


@pytest.fixture
def captured_exec(monkeypatch):
    """Capture the args to asyncio.create_subprocess_exec, return a configurable fake."""
    seen: dict[str, object] = {}

    async def factory(*args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs
        return seen.get("process", _FakeProcess(returncode=0))

    monkeypatch.setattr(compose_runner.asyncio, "create_subprocess_exec", factory)
    return seen


async def test_up_force_recreate_invokes_docker_compose_with_compose_file(captured_exec):
    await compose_runner.up_force_recreate(Path("/srv/atm10"))

    args = captured_exec["args"]
    assert args[0] == "docker"
    assert "compose" in args
    assert "-f" in args
    assert "/srv/atm10/docker-compose.yml" in args
    assert "up" in args
    assert "-d" in args
    assert "--force-recreate" in args


async def test_up_force_recreate_raises_on_nonzero_exit(captured_exec):
    captured_exec["process"] = _FakeProcess(returncode=1, stderr=b"compose: ENOENT")

    with pytest.raises(compose_runner.ComposeError) as exc_info:
        await compose_runner.up_force_recreate(Path("/srv/atm10"))

    assert "compose: ENOENT" in str(exc_info.value)


async def test_up_force_recreate_succeeds_on_zero_exit(captured_exec):
    captured_exec["process"] = _FakeProcess(returncode=0)

    # Should not raise.
    await compose_runner.up_force_recreate(Path("/srv/atm10"))
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_compose_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: mcontrol.compose_runner`.

- [ ] **Step 3: Implement `compose_runner.py`**

Create `src/mcontrol/compose_runner.py`:

```python
"""Async wrapper over `docker compose` (v2 plugin) for the slice-4
lifecycle path that needs `--force-recreate` semantics.

We shell out (rather than calling aiodocker directly) because the
per-server docker-compose.yml is the source of truth for the MC
container's full shape (image, env, volumes, networks). Re-implementing
that in aiodocker would mean parsing compose ourselves; ~50 MB of
docker-cli + compose-plugin in the runtime image is a better trade.
"""

import asyncio
from pathlib import Path


class ComposeError(RuntimeError):
    """Raised when `docker compose` exits non-zero."""


async def up_force_recreate(server_dir: Path) -> None:
    """Run `docker compose -f <server_dir>/docker-compose.yml up -d --force-recreate`.

    Raises ComposeError with the captured stderr on non-zero exit.
    """
    compose_file = server_dir / "docker-compose.yml"

    proc = await asyncio.create_subprocess_exec(
        "docker", "compose",
        "-f", str(compose_file),
        "up", "-d", "--force-recreate",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        message = stderr.decode("utf-8", errors="replace").strip() or "docker compose failed"
        raise ComposeError(message)
```

- [ ] **Step 4: Run to verify they pass**

```bash
uv run pytest tests/test_compose_runner.py -v
uv run pytest -v
```

Expected: 3 new tests pass; full suite green.

- [ ] **Step 5: Commit**

```bash
git add src/mcontrol/compose_runner.py tests/test_compose_runner.py
git commit -m "feat(slice4): compose_runner — async wrapper over \`docker compose\`

Used by the lifecycle path when an MC container's .env (RCON_PASSWORD)
has just been (re)written and we need a force-recreate so compose
picks up the new env. ComposeError surfaces stderr to the caller —
routes/lifecycle.py renders it as an inline error fragment."
```

---

# Task 7: `docker_client.py` extensions — start/stop/restart/logs/network/self_id

**Files:**
- Modify: `src/mcontrol/docker_client.py`
- Modify: `tests/test_docker_client.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_docker_client.py` (keep existing tests; reuse `_FakeDocker` / `_FakeContainers` patterns):

```python
class _FakeContainer:
    def __init__(self, name: str = "atm10", networks: dict | None = None):
        self.name = name
        self._started = False
        self._stopped = False
        self._restarted = False
        self._show_data = {
            "Name": f"/{name}",
            "NetworkSettings": {"Networks": networks or {"atm10_default": {}}},
        }

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._stopped = True

    async def restart(self) -> None:
        self._restarted = True

    async def show(self) -> dict:
        return self._show_data

    async def log(self, *, stdout=True, stderr=True, tail="all", follow=False):
        # aiodocker returns an async generator of strings. Tests substitute their own.
        for line in ["[INFO] starting", "[INFO] done"]:
            yield line


def _docker_with_named_container(monkeypatch, container: _FakeContainer):
    """Wire docker_client.aiodocker.Docker to return a fake whose
    .containers.get(name) yields the given container."""

    class _ContainersWithGet:
        async def get(self, name):  # noqa: ARG002
            return container

    class _Docker:
        def __init__(self, *_, **__):
            self.containers = _ContainersWithGet()

        async def close(self):
            pass

    monkeypatch.setattr(docker_client.aiodocker, "Docker", _Docker)
    return container


async def test_start_calls_container_start(env, monkeypatch):
    fake = _docker_with_named_container(monkeypatch, _FakeContainer())

    await docker_client.start("atm10")

    assert fake._started is True


async def test_stop_calls_container_stop(env, monkeypatch):
    fake = _docker_with_named_container(monkeypatch, _FakeContainer())

    await docker_client.stop("atm10")

    assert fake._stopped is True


async def test_restart_calls_container_restart(env, monkeypatch):
    fake = _docker_with_named_container(monkeypatch, _FakeContainer())

    await docker_client.restart("atm10")

    assert fake._restarted is True


async def test_logs_stream_yields_lines(env, monkeypatch):
    fake = _FakeContainer()

    async def fake_log_method(*, stdout, stderr, tail, follow):
        yield "boot line 1"
        yield "boot line 2"

    fake.log = fake_log_method
    _docker_with_named_container(monkeypatch, fake)

    lines = [line async for line in docker_client.logs_stream("atm10", tail=200)]

    assert lines == ["boot line 1", "boot line 2"]


async def test_find_network_name_returns_first_network(env, monkeypatch):
    _docker_with_named_container(
        monkeypatch,
        _FakeContainer(networks={"atm10_default": {}, "host": {}}),
    )

    name = await docker_client.find_network_name("atm10")

    assert name == "atm10_default"


async def test_find_network_name_returns_none_when_no_networks(env, monkeypatch):
    _docker_with_named_container(monkeypatch, _FakeContainer(networks={}))

    name = await docker_client.find_network_name("atm10")

    assert name is None


def test_self_container_id_reads_hostname_env(monkeypatch):
    monkeypatch.setenv("HOSTNAME", "abc123def456")

    assert docker_client.self_container_id() == "abc123def456"


async def test_attach_self_to_network_calls_connect(env, monkeypatch):
    connected: list[tuple[str, str]] = []

    class _Network:
        def __init__(self, name):
            self.name = name

        async def connect(self, *, container):
            connected.append((self.name, container))

    class _Networks:
        async def get(self, name):
            return _Network(name)

    class _Docker:
        def __init__(self, *_, **__):
            self.networks = _Networks()

        async def close(self):
            pass

    monkeypatch.setattr(docker_client.aiodocker, "Docker", _Docker)
    monkeypatch.setenv("HOSTNAME", "selfid")

    await docker_client.attach_self_to_network("atm10_default")

    assert connected == [("atm10_default", "selfid")]


async def test_detach_self_from_network_calls_disconnect(env, monkeypatch):
    disconnected: list[tuple[str, str]] = []

    class _Network:
        def __init__(self, name):
            self.name = name

        async def disconnect(self, *, container):
            disconnected.append((self.name, container))

    class _Networks:
        async def get(self, name):
            return _Network(name)

    class _Docker:
        def __init__(self, *_, **__):
            self.networks = _Networks()

        async def close(self):
            pass

    monkeypatch.setattr(docker_client.aiodocker, "Docker", _Docker)
    monkeypatch.setenv("HOSTNAME", "selfid")

    await docker_client.detach_self_from_network("atm10_default")

    assert disconnected == [("atm10_default", "selfid")]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_docker_client.py -v`
Expected: 8 new tests fail with `AttributeError: module 'mcontrol.docker_client' has no attribute 'start'` (etc.).

- [ ] **Step 3: Extend `docker_client.py`**

Replace `src/mcontrol/docker_client.py` with the full version below (preserves the existing `container_states_by_name` from Task 2):

```python
"""Thin async wrapper around aiodocker for the operations slice 4 needs:

- container_states_by_name() — discovery's existing read.
- start/stop/restart(name) — lifecycle controls.
- logs_stream(name, tail) — async generator of log lines for SSE.
- find_network_name(name) — picks the MC container's docker network so
  mcontrol can attach to it for RCON.
- attach_self_to_network / detach_self_from_network — the network attach
  dance the RCON SSE wraps with.
- self_container_id() — used by the attach/detach calls.
"""

import os
from collections.abc import AsyncIterator
from contextlib import suppress

import aiodocker

from mcontrol.settings import Settings


def _settings() -> Settings:
    return Settings()


def self_container_id() -> str:
    """Short docker container ID of the running mcontrol process.

    Docker sets HOSTNAME to the short container ID by default. If a
    deployment overrides hostname in compose, this assumption breaks —
    fall back to /etc/hostname.
    """
    return os.environ.get("HOSTNAME") or open("/etc/hostname").read().strip()


async def container_states_by_name() -> dict[str, str]:
    settings = _settings()
    try:
        docker = aiodocker.Docker(url=settings.docker_host)
    except Exception:
        return {}

    try:
        containers = await docker.containers.list(all=True)
        states: dict[str, str] = {}
        for c in containers:
            raw = c._container if hasattr(c, "_container") else {}
            names = raw.get("Names") or []
            if not names:
                continue
            name = names[0].lstrip("/")
            status = raw.get("State") or raw.get("Status", "unknown")
            states[name] = status
        return states
    except Exception:
        return {}
    finally:
        with suppress(Exception):
            await docker.close()


async def start(container_name: str) -> None:
    docker = aiodocker.Docker(url=_settings().docker_host)
    try:
        c = await docker.containers.get(container_name)
        await c.start()
    finally:
        with suppress(Exception):
            await docker.close()


async def stop(container_name: str) -> None:
    docker = aiodocker.Docker(url=_settings().docker_host)
    try:
        c = await docker.containers.get(container_name)
        await c.stop()
    finally:
        with suppress(Exception):
            await docker.close()


async def restart(container_name: str) -> None:
    docker = aiodocker.Docker(url=_settings().docker_host)
    try:
        c = await docker.containers.get(container_name)
        await c.restart()
    finally:
        with suppress(Exception):
            await docker.close()


async def logs_stream(
    container_name: str, *, tail: int = 200
) -> AsyncIterator[str]:
    """Async generator of log lines for a running container.

    Yields each line as a string (already decoded). Closes when the
    underlying aiodocker stream closes (caller disconnect, or container
    exit). Caller is responsible for catching cancellation.
    """
    docker = aiodocker.Docker(url=_settings().docker_host)
    try:
        c = await docker.containers.get(container_name)
        async for line in c.log(stdout=True, stderr=True, tail=tail, follow=True):
            yield line
    finally:
        with suppress(Exception):
            await docker.close()


async def find_network_name(container_name: str) -> str | None:
    """Return the name of the first non-host docker network the container
    is attached to, or None if it has none."""
    docker = aiodocker.Docker(url=_settings().docker_host)
    try:
        c = await docker.containers.get(container_name)
        info = await c.show()
        networks = info.get("NetworkSettings", {}).get("Networks", {}) or {}
        for name in networks:
            if name == "host":
                continue
            return name
        return None
    finally:
        with suppress(Exception):
            await docker.close()


async def attach_self_to_network(network_name: str) -> None:
    """Connect the mcontrol container to the given docker network. Idempotent
    in practice: if already connected, the API returns 403 which we suppress."""
    docker = aiodocker.Docker(url=_settings().docker_host)
    try:
        network = await docker.networks.get(network_name)
        with suppress(Exception):
            await network.connect(container=self_container_id())
    finally:
        with suppress(Exception):
            await docker.close()


async def detach_self_from_network(network_name: str) -> None:
    docker = aiodocker.Docker(url=_settings().docker_host)
    try:
        network = await docker.networks.get(network_name)
        with suppress(Exception):
            await network.disconnect(container=self_container_id())
    finally:
        with suppress(Exception):
            await docker.close()
```

- [ ] **Step 4: Run to verify they pass**

```bash
uv run pytest tests/test_docker_client.py -v
uv run pytest -v
```

Expected: ~13 docker_client tests green; full suite green.

- [ ] **Step 5: Commit**

```bash
git add src/mcontrol/docker_client.py tests/test_docker_client.py
git commit -m "feat(docker_client): start/stop/restart/logs/network/self_id

Adds the per-container operations slice 4 needs:
  - start / stop / restart for the lifecycle buttons.
  - logs_stream(name, tail=200) — async iterator of log lines, used by
    the SSE log endpoint.
  - find_network_name + attach_self_to_network + detach_self_from_network
    — the network-attach dance the RCON SSE wraps with.
  - self_container_id reads HOSTNAME (the short container ID Docker
    sets by default) with /etc/hostname as fallback.

All wrappers open a fresh aiodocker.Docker, run, and close in a
finally block. No connection pool — single-user scale doesn't need it."
```

---

# Task 8: `rcon.py` — bespoke async Source RCON client

**Files:**
- Create: `src/mcontrol/rcon.py`
- Create: `tests/test_rcon.py`

The Source RCON protocol (used by Minecraft):

- Each packet is `<length:int32 LE><id:int32 LE><type:int32 LE><body:bytes><null:byte><null:byte>`. `length` is the size of the packet excluding the length field itself.
- Types we use: `SERVERDATA_AUTH=3`, `SERVERDATA_AUTH_RESPONSE=2`, `SERVERDATA_EXECCOMMAND=2`, `SERVERDATA_RESPONSE_VALUE=0`.
- Auth: client sends type=3 with password; server replies with type=2 with id matching. id=-1 = auth failed.
- Exec: client sends type=2; server replies with one or more type=0 packets. For slice 4 we assume single-packet responses (max 4096 body bytes).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rcon.py`:

```python
"""End-to-end tests for the bespoke async RCON client against a fake
Source-protocol server built on asyncio.start_server.

The fake mirrors Minecraft's RCON: AUTH (type=3) → AUTH_RESPONSE (type=2,
id=match for ok, id=-1 for fail), EXEC (type=2) → RESPONSE_VALUE (type=0).
"""

import asyncio
import struct

import pytest

from mcontrol import rcon


def _pack(packet_id: int, packet_type: int, body: bytes) -> bytes:
    payload = struct.pack("<ii", packet_id, packet_type) + body + b"\x00\x00"
    length = len(payload)
    return struct.pack("<i", length) + payload


async def _read_packet(reader: asyncio.StreamReader) -> tuple[int, int, bytes]:
    length_bytes = await reader.readexactly(4)
    length = struct.unpack("<i", length_bytes)[0]
    payload = await reader.readexactly(length)
    packet_id, packet_type = struct.unpack("<ii", payload[:8])
    body = payload[8:-2]  # strip the two trailing null bytes
    return packet_id, packet_type, body


class _FakeRconServer:
    def __init__(self, password: str = "hunter2"):
        self.password = password
        self.received_commands: list[bytes] = []
        self.fail_auth = False
        self.exec_response = b"There are 3 of a max of 20 players online: alice, bob, carol"
        self._server: asyncio.base_events.Server | None = None
        self.host = "127.0.0.1"
        self.port = 0  # populated after start

    async def __aenter__(self):
        self._server = await asyncio.start_server(self._handler, host=self.host, port=0)
        # Pull the actual port out of the bound socket.
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *_):
        self._server.close()
        await self._server.wait_closed()

    async def _handler(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            # Auth packet first
            pid, ptype, body = await _read_packet(reader)
            assert ptype == 3, "first packet must be AUTH"
            ok = body.rstrip(b"\x00").decode() == self.password and not self.fail_auth
            response_id = pid if ok else -1
            writer.write(_pack(response_id, 2, b""))  # AUTH_RESPONSE
            await writer.drain()
            if not ok:
                writer.close()
                return

            # One or more EXEC packets
            while not reader.at_eof():
                try:
                    pid, ptype, body = await _read_packet(reader)
                except asyncio.IncompleteReadError:
                    break
                if ptype == 2:  # EXECCOMMAND
                    self.received_commands.append(body.rstrip(b"\x00"))
                    writer.write(_pack(pid, 0, self.exec_response))
                    await writer.drain()
        finally:
            writer.close()


async def test_connect_and_run_returns_response():
    async with _FakeRconServer() as server:
        client = await rcon.connect(server.host, server.port, "hunter2")
        try:
            response = await client.run("list")
            assert response == "There are 3 of a max of 20 players online: alice, bob, carol"
            assert server.received_commands == [b"list"]
        finally:
            await client.close()


async def test_connect_raises_on_bad_password():
    async with _FakeRconServer() as server:
        with pytest.raises(rcon.AuthenticationError):
            await rcon.connect(server.host, server.port, "wrong-password")


async def test_close_idempotent_when_run_twice():
    async with _FakeRconServer() as server:
        client = await rcon.connect(server.host, server.port, "hunter2")
        await client.close()
        # Second close must not raise.
        await client.close()


async def test_run_after_close_raises():
    async with _FakeRconServer() as server:
        client = await rcon.connect(server.host, server.port, "hunter2")
        await client.close()
        with pytest.raises(rcon.RconClosedError):
            await client.run("list")


async def test_run_handles_empty_response():
    async with _FakeRconServer() as server:
        server.exec_response = b""
        client = await rcon.connect(server.host, server.port, "hunter2")
        try:
            response = await client.run("op alice")
            assert response == ""
        finally:
            await client.close()
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_rcon.py -v`
Expected: FAIL — `ModuleNotFoundError: mcontrol.rcon`.

- [ ] **Step 3: Implement `rcon.py`**

Create `src/mcontrol/rcon.py`:

```python
"""Bespoke async client for the Source RCON protocol used by Minecraft.

Each packet:
    <length:int32 LE><id:int32 LE><type:int32 LE><body:bytes><null><null>
Length excludes itself.

Types used:
    SERVERDATA_AUTH                = 3
    SERVERDATA_AUTH_RESPONSE       = 2
    SERVERDATA_EXECCOMMAND         = 2
    SERVERDATA_RESPONSE_VALUE      = 0

Auth: send AUTH (type=3) with the password as the body. Server replies
with AUTH_RESPONSE (type=2). id=-1 means auth failed; otherwise it
echoes the request id.

Exec: send EXECCOMMAND (type=2). Server replies with one or more
RESPONSE_VALUE (type=0) packets. Slice 4 assumes single-packet
responses (max 4096 body bytes); this is sufficient for `list`,
`whitelist`, `op`, and the other commands the console uses. If a
response is fragmented, callers see only the first chunk.

Reference: https://wiki.vg/RCON
"""

import asyncio
import itertools
import struct

_AUTH = 3
_AUTH_RESPONSE = 2
_EXECCOMMAND = 2
_RESPONSE_VALUE = 0


class RconError(RuntimeError):
    pass


class AuthenticationError(RconError):
    pass


class RconClosedError(RconError):
    pass


class _RconConnection:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self._reader = reader
        self._writer = writer
        self._ids = itertools.count(1)
        self._closed = False

    async def run(self, command: str) -> str:
        if self._closed:
            raise RconClosedError("connection has been closed")
        packet_id = next(self._ids)
        await self._send(packet_id, _EXECCOMMAND, command.encode("utf-8"))
        response_id, response_type, body = await self._read()
        if response_type != _RESPONSE_VALUE:
            raise RconError(f"unexpected response type {response_type}")
        if response_id != packet_id:
            raise RconError(f"id mismatch: sent {packet_id}, got {response_id}")
        return body.decode("utf-8", errors="replace")

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._writer.close()
            await self._writer.wait_closed()
        except Exception:
            pass

    async def _send(self, packet_id: int, packet_type: int, body: bytes) -> None:
        payload = struct.pack("<ii", packet_id, packet_type) + body + b"\x00\x00"
        length = len(payload)
        self._writer.write(struct.pack("<i", length) + payload)
        await self._writer.drain()

    async def _read(self) -> tuple[int, int, bytes]:
        length_bytes = await self._reader.readexactly(4)
        length = struct.unpack("<i", length_bytes)[0]
        payload = await self._reader.readexactly(length)
        packet_id, packet_type = struct.unpack("<ii", payload[:8])
        body = payload[8:-2]
        return packet_id, packet_type, body


async def connect(host: str, port: int, password: str) -> _RconConnection:
    """Open and authenticate an RCON connection. Raises AuthenticationError
    if the server rejects the password."""
    reader, writer = await asyncio.open_connection(host, port)
    conn = _RconConnection(reader, writer)
    auth_id = next(conn._ids)
    await conn._send(auth_id, _AUTH, password.encode("utf-8"))
    response_id, response_type, _ = await conn._read()
    if response_type != _AUTH_RESPONSE:
        await conn.close()
        raise RconError(f"expected AUTH_RESPONSE, got {response_type}")
    if response_id == -1:
        await conn.close()
        raise AuthenticationError("RCON authentication failed")
    return conn
```

- [ ] **Step 4: Run to verify they pass**

```bash
uv run pytest tests/test_rcon.py -v
uv run pytest -v
```

Expected: 5 RCON tests pass; full suite green.

- [ ] **Step 5: Commit**

```bash
git add src/mcontrol/rcon.py tests/test_rcon.py
git commit -m "feat(slice4): bespoke async RCON client (~80 LOC)

Implements the Source RCON protocol against asyncio streams. Slice 4
needed an async client that fits SSE without an asyncio.to_thread
wrapper around mcrcon; adding ~80 lines of well-tested protocol code
beats pulling in a sync dep for ~7 lines of useful behaviour.

Single-packet response assumption: matches typical \`list\`, \`op\`,
\`whitelist\` outputs. Fragmented responses fall outside slice 4 and
will be addressed when an actual command produces one."
```

---

# Task 9: `routes/lifecycle.py` + `_state_pill.html`

**Files:**
- Create: `src/mcontrol/routes/lifecycle.py`
- Create: `src/mcontrol/templates/_state_pill.html`
- Create: `tests/test_lifecycle.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_lifecycle.py`:

```python
import pytest


@pytest.fixture
def fake_server_row(monkeypatch):
    rows: dict[str, dict] = {}

    def fake_get(name):
        return rows.get(name)

    from mcontrol import db

    monkeypatch.setattr(db, "get_server", fake_get)
    return rows


@pytest.fixture
def stub_db_writes(monkeypatch):
    seen: list[tuple[str, dict]] = []
    from mcontrol import db

    def cap(label):
        def fn(**kwargs):
            seen.append((label, kwargs))
        return fn

    monkeypatch.setattr(db, "set_rcon_password", cap("set_rcon_password"))
    monkeypatch.setattr(db, "update_server_state", cap("update_server_state"))
    return seen


@pytest.fixture
def stub_docker_and_compose(monkeypatch, tmp_path):
    from mcontrol import compose_runner, docker_client, env_writer, passwords

    started: list[str] = []
    stopped: list[str] = []
    restarted: list[str] = []
    composes: list[str] = []
    pwds: list[str] = []
    env_writes: list[tuple] = []

    async def fake_start(name): started.append(name)
    async def fake_stop(name): stopped.append(name)
    async def fake_restart(name): restarted.append(name)
    async def fake_up_force_recreate(server_dir): composes.append(str(server_dir))

    def fake_generate(): pwds.append("PWD"); return "PWD"

    def fake_write_rcon_password(path, pwd):
        env_writes.append((str(path), pwd))

    monkeypatch.setattr(docker_client, "start", fake_start)
    monkeypatch.setattr(docker_client, "stop", fake_stop)
    monkeypatch.setattr(docker_client, "restart", fake_restart)
    monkeypatch.setattr(compose_runner, "up_force_recreate", fake_up_force_recreate)
    monkeypatch.setattr(passwords, "generate", fake_generate)
    monkeypatch.setattr(env_writer, "write_rcon_password", fake_write_rcon_password)

    return {
        "started": started, "stopped": stopped, "restarted": restarted,
        "composes": composes, "pwds": pwds, "env_writes": env_writes,
    }


async def test_stop_calls_docker_stop_and_returns_state_pill(
    client, fake_server_row, stub_db_writes, stub_docker_and_compose
):
    fake_server_row["atm10"] = {
        "name": "atm10", "container_name": None, "dir": "/srv/atm10",
        "state": "running", "rcon_password": "existing-pwd",
    }

    response = await client.post("/servers/atm10/lifecycle/stop")

    assert response.status_code == 200
    assert "exited" in response.text  # state-pill text
    assert stub_docker_and_compose["stopped"] == ["atm10"]
    # update_server_state should have been called with the new state.
    assert ("update_server_state", {"name": "atm10", "state": "exited"}) in stub_db_writes


async def test_start_with_existing_password_uses_docker_start(
    client, fake_server_row, stub_db_writes, stub_docker_and_compose, tmp_path
):
    fake_server_row["atm10"] = {
        "name": "atm10", "container_name": None, "dir": str(tmp_path),
        "state": "exited", "rcon_password": "existing-pwd",
    }
    # Ensure the .env already has the same password so we DON'T force-recreate.
    (tmp_path / ".env").write_text("RCON_PASSWORD=existing-pwd\n")

    response = await client.post("/servers/atm10/lifecycle/start")

    assert response.status_code == 200
    assert "running" in response.text
    assert stub_docker_and_compose["started"] == ["atm10"]
    assert stub_docker_and_compose["composes"] == []
    # Password did not need regeneration.
    assert stub_docker_and_compose["pwds"] == []


async def test_start_generates_password_and_force_recreates_when_db_password_missing(
    client, fake_server_row, stub_db_writes, stub_docker_and_compose, tmp_path
):
    fake_server_row["atm10"] = {
        "name": "atm10", "container_name": None, "dir": str(tmp_path),
        "state": "exited", "rcon_password": None,
    }

    response = await client.post("/servers/atm10/lifecycle/start")

    assert response.status_code == 200
    assert stub_docker_and_compose["pwds"] == ["PWD"]
    assert ("set_rcon_password", {"name": "atm10", "password": "PWD"}) in stub_db_writes
    assert stub_docker_and_compose["env_writes"] == [(str(tmp_path / ".env"), "PWD")]
    # Force-recreate, not plain start.
    assert stub_docker_and_compose["started"] == []
    assert stub_docker_and_compose["composes"] == [str(tmp_path)]


async def test_start_force_recreates_when_disk_env_diverges_from_db(
    client, fake_server_row, stub_db_writes, stub_docker_and_compose, tmp_path
):
    fake_server_row["atm10"] = {
        "name": "atm10", "container_name": None, "dir": str(tmp_path),
        "state": "exited", "rcon_password": "DB_PWD",
    }
    (tmp_path / ".env").write_text("RCON_PASSWORD=ON_DISK_DIFFERENT\n")

    response = await client.post("/servers/atm10/lifecycle/start")

    assert response.status_code == 200
    assert stub_docker_and_compose["env_writes"] == [(str(tmp_path / ".env"), "DB_PWD")]
    assert stub_docker_and_compose["composes"] == [str(tmp_path)]
    assert stub_docker_and_compose["started"] == []


async def test_restart_calls_docker_restart_when_env_already_matches(
    client, fake_server_row, stub_db_writes, stub_docker_and_compose, tmp_path
):
    fake_server_row["atm10"] = {
        "name": "atm10", "container_name": None, "dir": str(tmp_path),
        "state": "running", "rcon_password": "DB_PWD",
    }
    (tmp_path / ".env").write_text("RCON_PASSWORD=DB_PWD\n")

    response = await client.post("/servers/atm10/lifecycle/restart")

    assert response.status_code == 200
    assert stub_docker_and_compose["restarted"] == ["atm10"]
    assert stub_docker_and_compose["composes"] == []


async def test_lifecycle_returns_404_for_unknown_server(client, fake_server_row, stub_docker_and_compose):
    response = await client.post("/servers/unknown/lifecycle/start")
    assert response.status_code == 404


async def test_lifecycle_uses_container_name_override(
    client, fake_server_row, stub_db_writes, stub_docker_and_compose, tmp_path
):
    fake_server_row["atm10"] = {
        "name": "atm10", "container_name": "atm10-prod", "dir": str(tmp_path),
        "state": "running", "rcon_password": "DB_PWD",
    }
    (tmp_path / ".env").write_text("RCON_PASSWORD=DB_PWD\n")

    await client.post("/servers/atm10/lifecycle/stop")

    assert stub_docker_and_compose["stopped"] == ["atm10-prod"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_lifecycle.py -v`
Expected: every test FAILs with 404 (route not registered yet).

- [ ] **Step 3: Create the state-pill partial**

Create `src/mcontrol/templates/_state_pill.html`:

```html
<span id="state-pill"
      class="server-detail__state server-detail__state--{{ state }}">
  {{ state }}
</span>
```

- [ ] **Step 4: Implement the lifecycle route**

Create `src/mcontrol/routes/lifecycle.py`:

```python
"""HTMX-driven Start / Stop / Restart for a server.

Each handler does the minimum required:

  Stop  → docker_client.stop(container_name); db.update_server_state(..., "exited")
  Start → if rcon_password missing: generate, persist, write .env, force-recreate.
          elif disk .env differs from DB rcon_password: write .env, force-recreate.
          else: docker_client.start(container_name).
          db.update_server_state(..., "running")
  Restart → same as Start, but uses docker_client.restart when .env already matches.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from mcontrol import compose_runner, db, docker_client, env_writer, passwords
from mcontrol.templates import templates

router = APIRouter()


def _pill(request: Request, state: str) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="_state_pill.html",
        context={"state": state},
    )


def _ensure_env_matches_db(server: dict) -> bool:
    """Return True iff the .env on disk matches the DB rcon_password.
    If the password is missing in DB, it's generated and persisted.
    Returns True when no force-recreate is needed (DB matches disk),
    False otherwise (caller must force-recreate)."""
    name = server["name"]
    server_dir = Path(server["dir"])
    env_path = server_dir / ".env"

    db_password = server.get("rcon_password")
    if not db_password:
        db_password = passwords.generate()
        db.set_rcon_password(name=name, password=db_password)

    on_disk = env_writer.read_rcon_password(env_path)
    if on_disk == db_password:
        return True

    env_writer.write_rcon_password(env_path, db_password)
    return False


@router.post("/servers/{name}/lifecycle/start", response_class=HTMLResponse)
async def start(request: Request, name: str) -> HTMLResponse:
    server = db.get_server(name)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")

    container_name = db.container_name_for(server)
    matches = _ensure_env_matches_db(server)
    if matches:
        await docker_client.start(container_name)
    else:
        await compose_runner.up_force_recreate(Path(server["dir"]))
    db.update_server_state(name=name, state="running")
    return _pill(request, "running")


@router.post("/servers/{name}/lifecycle/stop", response_class=HTMLResponse)
async def stop(request: Request, name: str) -> HTMLResponse:
    server = db.get_server(name)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")

    await docker_client.stop(db.container_name_for(server))
    db.update_server_state(name=name, state="exited")
    return _pill(request, "exited")


@router.post("/servers/{name}/lifecycle/restart", response_class=HTMLResponse)
async def restart(request: Request, name: str) -> HTMLResponse:
    server = db.get_server(name)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")

    container_name = db.container_name_for(server)
    matches = _ensure_env_matches_db(server)
    if matches:
        await docker_client.restart(container_name)
    else:
        await compose_runner.up_force_recreate(Path(server["dir"]))
    db.update_server_state(name=name, state="running")
    return _pill(request, "running")
```

- [ ] **Step 5: Register the router in `main.py`**

Read the current `src/mcontrol/main.py`. Update the imports to include `lifecycle` and add the include line. The full file should now be:

```python
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from mcontrol import discovery
from mcontrol.routes import home, lifecycle, server
from mcontrol.settings import Settings

STATIC_DIR = Path(__file__).parent / "static"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("mcontrol")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    base_path = Path(settings.server_base_path)
    try:
        count = await discovery.run_discovery(base_path)
        logger.info("discovery: %d server dir(s) seen under %s", count, base_path)
    except Exception:
        logger.exception("discovery failed; continuing without it")
    yield


def create_app() -> FastAPI:
    settings = Settings()
    app = FastAPI(title="mcontrol", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(home.router)
    app.include_router(server.router)
    app.include_router(lifecycle.router)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
```

(Note: this assumes the log-config commit from PR #7 has merged into main and the slice-4 branch has been rebased. If not, the `logging.basicConfig(...)` block above won't be present yet — leave it alone in that case; the main change here is registering `lifecycle.router`.)

- [ ] **Step 6: Run lifecycle tests + full suite**

```bash
uv run pytest tests/test_lifecycle.py -v
uv run pytest -v
```

Expected: 7 lifecycle tests green; full suite green.

- [ ] **Step 7: Commit**

```bash
git add src/mcontrol/routes/lifecycle.py \
        src/mcontrol/templates/_state_pill.html \
        src/mcontrol/main.py \
        tests/test_lifecycle.py
git commit -m "feat(routes): HTMX-driven lifecycle (start/stop/restart)

Each lifecycle POST returns an HTMX-swappable state-pill partial.
Start/Restart paths reconcile .env against the DB rcon_password
before deciding plain docker start (env matches) vs compose
force-recreate (env diverged or password just generated).
Container name lookup goes through db.container_name_for so an
operator-edited container_name override is honoured."
```

---

# Task 10: `routes/logs.py` SSE + log pane

**Files:**
- Create: `src/mcontrol/routes/logs.py`
- Create: `src/mcontrol/templates/_log_pane.html`
- Create: `tests/test_logs.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_logs.py`:

```python
import pytest


@pytest.fixture
def fake_logs(monkeypatch):
    """Stub docker_client.logs_stream to yield predefined lines."""
    lines: list[str] = []

    async def fake(name, *, tail=200):
        for line in lines:
            yield line

    from mcontrol import docker_client

    monkeypatch.setattr(docker_client, "logs_stream", fake)
    return lines


@pytest.fixture
def fake_get_server(monkeypatch):
    rows: dict[str, dict] = {}
    from mcontrol import db
    monkeypatch.setattr(db, "get_server", lambda n: rows.get(n))
    return rows


async def test_logs_endpoint_returns_404_for_unknown_server(client, fake_get_server, fake_logs):
    response = await client.get("/servers/unknown/logs")
    assert response.status_code == 404


async def test_logs_endpoint_streams_sse_with_each_line(client, fake_get_server, fake_logs):
    fake_get_server["atm10"] = {"name": "atm10", "container_name": None, "dir": "/srv/atm10"}
    fake_logs.extend(["[INFO] starting", "[INFO] done"])

    async with client.stream("GET", "/servers/atm10/logs") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

        body = b""
        async for chunk in response.aiter_bytes():
            body += chunk
        text = body.decode("utf-8")

    assert "data: [INFO] starting" in text
    assert "data: [INFO] done" in text


async def test_logs_endpoint_uses_container_name_override(client, fake_get_server, monkeypatch):
    fake_get_server["atm10"] = {
        "name": "atm10", "container_name": "atm10-prod", "dir": "/srv/atm10",
    }
    seen: list[str] = []

    async def fake(name, *, tail=200):
        seen.append(name)
        return
        yield  # pragma: no cover  (make this an async generator)

    from mcontrol import docker_client
    monkeypatch.setattr(docker_client, "logs_stream", fake)

    async with client.stream("GET", "/servers/atm10/logs") as response:
        async for _ in response.aiter_bytes():
            pass

    assert seen == ["atm10-prod"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_logs.py -v`
Expected: all FAIL with 404.

- [ ] **Step 3: Create the log pane partial**

Create `src/mcontrol/templates/_log_pane.html`:

```html
<section class="log-pane">
  <p class="t-eyebrow">Logs</p>
  <pre id="log-stream"
       class="log-pane__stream"
       hx-ext="sse"
       sse-connect="/servers/{{ server.name }}/logs"
       sse-swap="message"
       hx-swap="beforeend"></pre>
</section>
```

- [ ] **Step 4: Implement the route**

Create `src/mcontrol/routes/logs.py`:

```python
"""Server-Sent Events endpoint streaming `docker logs --follow` for a
given server. Consumed by the log pane on the detail page (HTMX SSE
extension)."""

from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from mcontrol import db, docker_client

router = APIRouter()


async def _sse(container_name: str) -> AsyncIterator[bytes]:
    async for line in docker_client.logs_stream(container_name, tail=200):
        # Each line becomes one SSE message. \n inside a line would split
        # the SSE payload, so flatten any internal newlines.
        flat = line.replace("\r", "").replace("\n", " ")
        yield f"data: {flat}\n\n".encode("utf-8")


@router.get("/servers/{name}/logs")
async def stream(name: str) -> StreamingResponse:
    server = db.get_server(name)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")

    container_name = db.container_name_for(server)
    return StreamingResponse(_sse(container_name), media_type="text/event-stream")
```

- [ ] **Step 5: Register the router in `main.py`**

Add `logs` to the imports and the `include_router` call:

```python
from mcontrol.routes import home, lifecycle, logs, server
...
    app.include_router(logs.router)
```

- [ ] **Step 6: Run logs tests + full suite**

```bash
uv run pytest tests/test_logs.py -v
uv run pytest -v
```

Expected: 3 logs tests green; full suite green.

- [ ] **Step 7: Commit**

```bash
git add src/mcontrol/routes/logs.py \
        src/mcontrol/templates/_log_pane.html \
        src/mcontrol/main.py \
        tests/test_logs.py
git commit -m "feat(routes): SSE log stream for /servers/{name}

Wraps docker_client.logs_stream as a text/event-stream response.
The HTMX SSE extension on the client side appends each \`data:\`
message to a <pre> with hx-swap=beforeend. Multi-line log entries
get their internal newlines flattened so they don't split the SSE
payload."
```

---

# Task 11: `routes/console.py` SSE + POST + console pane

**Files:**
- Create: `src/mcontrol/routes/console.py`
- Create: `src/mcontrol/templates/_console_pane.html`
- Create: `tests/test_console.py`

The console has two endpoints:
- `GET /servers/{name}/rcon` (SSE) — opens an RCON connection (after attaching mcontrol to the MC's docker network), streams server output as `data:` messages, holds connection until disconnect.
- `POST /servers/{name}/rcon` (form, body `command=...`) — looks up the open SSE-side connection by server name, sends the command, the response flows back through the SSE stream.

The shared state — one `_RconConnection` per server — lives in a module-level `dict[str, _RconConnection]`. POST returns a tiny HTMX-friendly fragment (or 404 if no SSE is open).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_console.py`:

```python
import asyncio

import pytest


@pytest.fixture
def fake_get_server(monkeypatch):
    rows: dict[str, dict] = {}
    from mcontrol import db
    monkeypatch.setattr(db, "get_server", lambda n: rows.get(n))
    return rows


@pytest.fixture
def fake_docker_network(monkeypatch):
    from mcontrol import docker_client

    attaches: list[str] = []
    detaches: list[str] = []

    async def fake_find(name):
        return f"{name}_default"

    async def fake_attach(network):
        attaches.append(network)

    async def fake_detach(network):
        detaches.append(network)

    monkeypatch.setattr(docker_client, "find_network_name", fake_find)
    monkeypatch.setattr(docker_client, "attach_self_to_network", fake_attach)
    monkeypatch.setattr(docker_client, "detach_self_from_network", fake_detach)

    return {"attaches": attaches, "detaches": detaches}


class _FakeRconConnection:
    def __init__(self):
        self.commands: list[str] = []
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self.closed = False

    async def run(self, command: str) -> str:
        self.commands.append(command)
        return f"ack: {command}"

    async def close(self):
        self.closed = True


@pytest.fixture
def fake_rcon(monkeypatch):
    captured: dict[str, _FakeRconConnection] = {}

    async def fake_connect(host, port, password):
        conn = _FakeRconConnection()
        captured["conn"] = conn
        captured["host"] = host
        captured["port"] = port
        captured["password"] = password
        return conn

    from mcontrol import rcon
    monkeypatch.setattr(rcon, "connect", fake_connect)
    return captured


async def test_rcon_get_returns_404_for_unknown_server(client, fake_get_server, fake_docker_network):
    response = await client.get("/servers/unknown/rcon")
    assert response.status_code == 404


async def test_rcon_get_attaches_then_detaches_network(
    client, fake_get_server, fake_docker_network, fake_rcon
):
    fake_get_server["atm10"] = {
        "name": "atm10", "container_name": None, "dir": "/srv/atm10",
        "rcon_password": "hunter2",
    }

    async with client.stream("GET", "/servers/atm10/rcon") as response:
        assert response.status_code == 200
        # Read the first SSE message then close — the test-side disconnect
        # should trigger the route's finally block.
        async for chunk in response.aiter_bytes():
            if b"data:" in chunk:
                break

    # The route should have attached on entry and detached on exit.
    assert fake_docker_network["attaches"] == ["atm10_default"]
    assert fake_docker_network["detaches"] == ["atm10_default"]


async def test_rcon_get_returns_424_when_password_missing(
    client, fake_get_server, fake_docker_network, fake_rcon
):
    fake_get_server["atm10"] = {
        "name": "atm10", "container_name": None, "dir": "/srv/atm10",
        "rcon_password": None,
    }
    response = await client.get("/servers/atm10/rcon")
    assert response.status_code == 424


async def test_rcon_post_returns_409_when_no_open_session(
    client, fake_get_server, fake_docker_network, fake_rcon
):
    fake_get_server["atm10"] = {
        "name": "atm10", "container_name": None, "dir": "/srv/atm10",
        "rcon_password": "hunter2",
    }
    response = await client.post("/servers/atm10/rcon", data={"command": "list"})
    assert response.status_code == 409
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_console.py -v`
Expected: all FAIL with 404.

- [ ] **Step 3: Create the console pane partial**

Create `src/mcontrol/templates/_console_pane.html`:

```html
<section class="console-pane">
  <p class="t-eyebrow">RCON Console</p>
  <pre id="console-stream"
       class="console-pane__stream"
       hx-ext="sse"
       sse-connect="/servers/{{ server.name }}/rcon"
       sse-swap="message"
       hx-swap="beforeend"></pre>
  <form class="console-pane__input"
        hx-post="/servers/{{ server.name }}/rcon"
        hx-swap="none">
    <input type="text" name="command" placeholder="say hello" autocomplete="off" required>
    <button type="submit">Send</button>
  </form>
</section>
```

- [ ] **Step 4: Implement the console route**

Create `src/mcontrol/routes/console.py`:

```python
"""SSE-streamed RCON console + POST endpoint for command submission.

Slice-4 model: one open SSE per server at a time. The route attaches
the mcontrol container to the MC's docker network on connect, opens an
RCON connection to <container_name>:25575, and streams server output
back as SSE `data:` messages. POST /servers/{name}/rcon (form-encoded
command=...) finds the live connection by server name and submits the
command; the response flows back through the SSE stream.

If no SSE is open for a server, POST returns 409 ("open the console
first").
"""

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse

from mcontrol import db, docker_client, rcon

router = APIRouter()

_RCON_PORT = 25575
# Server name → live RconConnection, populated by SSE handler, cleared on disconnect.
_active_connections: dict[str, rcon._RconConnection] = {}
# Server name → asyncio.Queue[str] of output lines (responses from POST flow back here).
_output_queues: dict[str, asyncio.Queue] = {}


async def _stream(name: str, container_name: str, password: str) -> AsyncIterator[bytes]:
    network_name = await docker_client.find_network_name(container_name)
    if network_name is None:
        yield b"data: [error] no docker network found for container\n\n"
        return

    await docker_client.attach_self_to_network(network_name)
    try:
        conn = await rcon.connect(container_name, _RCON_PORT, password)
        queue: asyncio.Queue = asyncio.Queue()
        _active_connections[name] = conn
        _output_queues[name] = queue

        try:
            yield b"data: [info] rcon connected\n\n"
            while True:
                # Wait for output that the POST handler queued for us, or send
                # a periodic keep-alive so proxies don't drop the SSE.
                try:
                    line = await asyncio.wait_for(queue.get(), timeout=20.0)
                except asyncio.TimeoutError:
                    yield b": keepalive\n\n"
                    continue
                yield f"data: {line}\n\n".encode("utf-8")
        finally:
            _active_connections.pop(name, None)
            _output_queues.pop(name, None)
            await conn.close()
    finally:
        await docker_client.detach_self_from_network(network_name)


@router.get("/servers/{name}/rcon")
async def stream(name: str) -> StreamingResponse:
    server = db.get_server(name)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")

    password = server.get("rcon_password")
    if not password:
        raise HTTPException(
            status_code=424,
            detail="rcon_password not yet set — start the server first to generate one",
        )

    container_name = db.container_name_for(server)
    return StreamingResponse(
        _stream(name, container_name, password),
        media_type="text/event-stream",
    )


@router.post("/servers/{name}/rcon", response_class=HTMLResponse)
async def submit(name: str, command: str = Form(...)) -> HTMLResponse:
    if name not in _active_connections:
        raise HTTPException(status_code=409, detail="open the console first")
    conn = _active_connections[name]
    queue = _output_queues[name]
    response = await conn.run(command)
    # Echo the command + response into the SSE stream.
    await queue.put(f"> {command}")
    if response:
        await queue.put(response)
    return HTMLResponse("", status_code=204)
```

- [ ] **Step 5: Register the router in `main.py`**

Add `console` to imports and `include_router`:

```python
from mcontrol.routes import bindings, console, home, lifecycle, logs, server  # bindings added in Task 12
...
    app.include_router(console.router)
```

(For Task 11, register `console` only; `bindings` lands in Task 12 and is added then.)

- [ ] **Step 6: Run console tests + full suite**

```bash
uv run pytest tests/test_console.py -v
uv run pytest -v
```

Expected: 4 console tests green; full suite green.

- [ ] **Step 7: Commit**

```bash
git add src/mcontrol/routes/console.py \
        src/mcontrol/templates/_console_pane.html \
        src/mcontrol/main.py \
        tests/test_console.py
git commit -m "feat(routes): RCON console (SSE output + POST submit)

GET /servers/{name}/rcon — attaches the panel container to the MC's
docker network, opens an RCON connection, streams output as SSE.
POST /servers/{name}/rcon — finds the live connection by server name,
submits the command, response flows back through the SSE stream.

Module-level _active_connections + _output_queues track one open
session per server. Detach + close on stream end (caller disconnect or
inner failure)."
```

---

# Task 12: `routes/bindings.py` + bindings card / form

**Files:**
- Create: `src/mcontrol/routes/bindings.py`
- Create: `src/mcontrol/templates/_bindings_card.html`
- Create: `src/mcontrol/templates/_bindings_form.html`
- Create: `tests/test_bindings.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_bindings.py`:

```python
import pytest


@pytest.fixture
def fake_db(monkeypatch):
    rows: dict[str, dict] = {}
    updates: list[dict] = []

    from mcontrol import db

    monkeypatch.setattr(db, "get_server", lambda n: rows.get(n))
    monkeypatch.setattr(db, "update_bindings", lambda **kw: updates.append(kw))

    return {"rows": rows, "updates": updates}


async def test_bindings_card_returns_404_for_unknown_server(client, fake_db):
    response = await client.get("/servers/unknown/bindings")
    assert response.status_code == 404


async def test_bindings_card_renders_current_values(client, fake_db):
    fake_db["rows"]["atm10"] = {
        "name": "atm10",
        "container_name": "atm10-prod",
        "dir": "/srv/atm10",
    }

    response = await client.get("/servers/atm10/bindings")

    assert response.status_code == 200
    assert "atm10-prod" in response.text
    assert "/srv/atm10" in response.text


async def test_bindings_form_renders_when_edit_query_param_set(client, fake_db):
    fake_db["rows"]["atm10"] = {
        "name": "atm10", "container_name": None, "dir": "/srv/atm10",
    }

    response = await client.get("/servers/atm10/bindings?edit=1")

    assert response.status_code == 200
    assert 'name="container_name"' in response.text
    assert 'name="dir"' in response.text
    # Falls back placeholder when override is null.
    assert "/srv/atm10" in response.text


async def test_bindings_post_persists_overrides(client, fake_db):
    fake_db["rows"]["atm10"] = {
        "name": "atm10", "container_name": None, "dir": "/srv/atm10",
    }

    response = await client.post(
        "/servers/atm10/bindings",
        data={"container_name": "atm10-prod", "dir": "/operator/edited/path"},
    )

    assert response.status_code == 200
    assert fake_db["updates"] == [{
        "name": "atm10",
        "container_name": "atm10-prod",
        "dir": "/operator/edited/path",
    }]
    # Returns the read-only card with the new values.
    assert "atm10-prod" in response.text
    assert "/operator/edited/path" in response.text


async def test_bindings_post_clears_container_name_when_empty(client, fake_db):
    fake_db["rows"]["atm10"] = {
        "name": "atm10", "container_name": "atm10-prod", "dir": "/srv/atm10",
    }

    response = await client.post(
        "/servers/atm10/bindings",
        data={"container_name": "", "dir": "/srv/atm10"},
    )

    assert response.status_code == 200
    assert fake_db["updates"] == [{
        "name": "atm10",
        "container_name": None,
        "dir": "/srv/atm10",
    }]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_bindings.py -v`
Expected: all FAIL with 404.

- [ ] **Step 3: Create the bindings card partial**

Create `src/mcontrol/templates/_bindings_card.html`:

```html
<section class="bindings-card" id="bindings">
  <header class="bindings-card__head">
    <p class="t-eyebrow">Bindings</p>
    <a class="bindings-card__edit"
       hx-get="/servers/{{ server.name }}/bindings?edit=1"
       hx-target="#bindings"
       hx-swap="outerHTML"
       href="#">Edit</a>
  </header>
  <dl class="bindings-card__body">
    <dt class="t-caption">container name</dt>
    <dd>
      {% if server.container_name %}
        <code>{{ server.container_name }}</code>
      {% else %}
        <span class="t-muted">(falls back to <code>{{ server.name }}</code>)</span>
      {% endif %}
    </dd>
    <dt class="t-caption">directory</dt>
    <dd><code>{{ server.dir }}</code></dd>
  </dl>
</section>
```

- [ ] **Step 4: Create the bindings form partial**

Create `src/mcontrol/templates/_bindings_form.html`:

```html
<section class="bindings-card" id="bindings">
  <p class="t-eyebrow">Bindings</p>
  <form class="bindings-form"
        hx-post="/servers/{{ server.name }}/bindings"
        hx-target="#bindings"
        hx-swap="outerHTML">
    <label>
      <span class="t-caption">container name</span>
      <input type="text"
             name="container_name"
             value="{{ server.container_name or '' }}"
             placeholder="{{ server.name }}">
    </label>
    <label>
      <span class="t-caption">directory</span>
      <input type="text"
             name="dir"
             value="{{ server.dir }}">
    </label>
    <div class="bindings-form__actions">
      <button type="submit">Save</button>
      <a hx-get="/servers/{{ server.name }}/bindings"
         hx-target="#bindings"
         hx-swap="outerHTML"
         href="#">Cancel</a>
    </div>
  </form>
</section>
```

- [ ] **Step 5: Implement the route**

Create `src/mcontrol/routes/bindings.py`:

```python
"""HTMX-driven inline edit for the per-server `container_name` override
and `dir`. Decision 021 — the operator's safety valve against drift."""

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from mcontrol import db
from mcontrol.templates import templates

router = APIRouter()


def _card(request: Request, server: dict) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="_bindings_card.html",
        context={"server": server},
    )


def _form(request: Request, server: dict) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="_bindings_form.html",
        context={"server": server},
    )


@router.get("/servers/{name}/bindings", response_class=HTMLResponse)
async def get(request: Request, name: str, edit: int = 0) -> HTMLResponse:
    server = db.get_server(name)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")
    if edit:
        return _form(request, server)
    return _card(request, server)


@router.post("/servers/{name}/bindings", response_class=HTMLResponse)
async def post(
    request: Request,
    name: str,
    container_name: str = Form(""),
    dir: str = Form(...),
) -> HTMLResponse:
    server = db.get_server(name)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")

    # Empty string means "clear the override and fall back to name".
    cn_value: str | None = container_name.strip() or None
    db.update_bindings(name=name, container_name=cn_value, dir=dir)

    refreshed = {**server, "container_name": cn_value, "dir": dir}
    return _card(request, refreshed)
```

- [ ] **Step 6: Register the router**

Update `main.py`:

```python
from mcontrol.routes import bindings, console, home, lifecycle, logs, server
...
    app.include_router(bindings.router)
```

- [ ] **Step 7: Run bindings tests + full suite**

```bash
uv run pytest tests/test_bindings.py -v
uv run pytest -v
```

Expected: 5 bindings tests green; full suite green.

- [ ] **Step 8: Commit**

```bash
git add src/mcontrol/routes/bindings.py \
        src/mcontrol/templates/_bindings_card.html \
        src/mcontrol/templates/_bindings_form.html \
        src/mcontrol/main.py \
        tests/test_bindings.py
git commit -m "feat(routes): inline bindings edit (container_name + dir)

GET /servers/{name}/bindings → read-only card.
GET /servers/{name}/bindings?edit=1 → HTMX form (Edit button swap).
POST /servers/{name}/bindings → persists via db.update_bindings,
returns the refreshed read-only card. Empty container_name clears
the override (back to falling back to servers.name)."
```

---

# Task 13: Wire the new affordances into `server_detail.html` + extend `app.css`

**Files:**
- Modify: `src/mcontrol/templates/server_detail.html`
- Modify: `src/mcontrol/static/app.css`
- Modify: `tests/test_server_detail.py`

- [ ] **Step 1: Update test expectations**

Edit `tests/test_server_detail.py` so the existing tests still pass and one new test asserts the slice-4 affordances render. Read the current file first; replace the file with:

```python
import pytest


@pytest.fixture
def fake_get_server(monkeypatch):
    rows: dict[str, dict | None] = {}

    from mcontrol import db
    monkeypatch.setattr(db, "get_server", rows.get)
    return rows


async def test_server_detail_returns_404_when_unknown(client, fake_get_server):
    response = await client.get("/servers/does-not-exist")

    assert response.status_code == 404


async def test_server_detail_renders_known_server(client, fake_get_server):
    fake_get_server["atm10"] = {
        "name": "atm10",
        "container_name": None,
        "dir": "/home/abstract/servers/minecraft/atm10",
        "image_base": "eclipse-temurin:21-jre",
        "state": "running",
        "variables": {"memory_budget_gb": 12, "port": 25565},
        "rcon_password": "set",
        "created_at": "2026-04-29T10:00:00Z",
        "updated_at": "2026-04-29T10:00:00Z",
    }

    response = await client.get("/servers/atm10")

    assert response.status_code == 200
    body = response.text
    assert "atm10" in body
    assert "/home/abstract/servers/minecraft/atm10" in body
    assert "eclipse-temurin:21-jre" in body
    assert "running" in body
    assert "memory_budget_gb" in body
    assert "25565" in body


async def test_server_detail_renders_lifecycle_buttons(client, fake_get_server):
    fake_get_server["atm10"] = _row("atm10")
    response = await client.get("/servers/atm10")
    body = response.text
    assert 'hx-post="/servers/atm10/lifecycle/start"' in body
    assert 'hx-post="/servers/atm10/lifecycle/stop"' in body
    assert 'hx-post="/servers/atm10/lifecycle/restart"' in body


async def test_server_detail_renders_log_pane(client, fake_get_server):
    fake_get_server["atm10"] = _row("atm10")
    response = await client.get("/servers/atm10")
    assert 'sse-connect="/servers/atm10/logs"' in response.text


async def test_server_detail_renders_console_pane(client, fake_get_server):
    fake_get_server["atm10"] = _row("atm10")
    response = await client.get("/servers/atm10")
    body = response.text
    assert 'sse-connect="/servers/atm10/rcon"' in body
    assert 'hx-post="/servers/atm10/rcon"' in body


async def test_server_detail_renders_bindings_card(client, fake_get_server):
    fake_get_server["atm10"] = _row("atm10")
    response = await client.get("/servers/atm10")
    body = response.text
    assert "Bindings" in body
    assert 'hx-get="/servers/atm10/bindings?edit=1"' in body


async def test_server_detail_handles_null_image_base(client, fake_get_server):
    fake_get_server["fresh"] = _row("fresh", image_base=None, state="unknown")

    response = await client.get("/servers/fresh")

    assert response.status_code == 200
    assert "fresh" in response.text


async def test_server_detail_links_back_to_home(client, fake_get_server):
    fake_get_server["atm10"] = _row("atm10")
    response = await client.get("/servers/atm10")
    assert 'href="/"' in response.text


def _row(name: str, *, image_base: str | None = "eclipse-temurin:21-jre", state: str = "running") -> dict:
    return {
        "name": name,
        "container_name": None,
        "dir": f"/srv/{name}",
        "image_base": image_base,
        "state": state,
        "variables": {},
        "rcon_password": None,
        "created_at": "2026-04-29T10:00:00Z",
        "updated_at": "2026-04-29T10:00:00Z",
    }
```

- [ ] **Step 2: Run the existing tests to confirm they fail on the new assertions**

Run: `uv run pytest tests/test_server_detail.py -v`
Expected: FAIL on the four new assertions (`test_server_detail_renders_lifecycle_buttons`, `_log_pane`, `_console_pane`, `_bindings_card`).

- [ ] **Step 3: Replace `templates/server_detail.html` with the wired version**

```html
{% extends "base.html" %}

{% block title %}{{ server.name }} — mcontrol{% endblock %}

{% block main %}
<section class="server-detail-layout">
  <p class="t-eyebrow"><a href="/">← all servers</a></p>
  <h2 class="t-h3">{{ server.name }}</h2>

  <div class="lifecycle-row">
    {% include "_state_pill.html" with context %}
    <div class="lifecycle-row__buttons">
      <button class="lifecycle-button"
              hx-post="/servers/{{ server.name }}/lifecycle/start"
              hx-target="#state-pill"
              hx-swap="outerHTML">Start</button>
      <button class="lifecycle-button"
              hx-post="/servers/{{ server.name }}/lifecycle/stop"
              hx-target="#state-pill"
              hx-swap="outerHTML">Stop</button>
      <button class="lifecycle-button"
              hx-post="/servers/{{ server.name }}/lifecycle/restart"
              hx-target="#state-pill"
              hx-swap="outerHTML">Restart</button>
    </div>
  </div>

  <dl class="server-detail">
    <dt class="t-caption">directory</dt>
    <dd><code>{{ server.dir }}</code></dd>

    <dt class="t-caption">base image</dt>
    <dd>{% if server.image_base %}<code>{{ server.image_base }}</code>{% else %}<span class="t-muted">—</span>{% endif %}</dd>

    <dt class="t-caption">variables</dt>
    <dd>
      {% if server.variables %}
        <ul class="kv-list">
          {% for key, value in server.variables.items() %}
            <li><code>{{ key }}</code> = <code>{{ value }}</code></li>
          {% endfor %}
        </ul>
      {% else %}
        <span class="t-muted">no variables set</span>
      {% endif %}
    </dd>

    <dt class="t-caption">last seen</dt>
    <dd>{{ server.updated_at }}</dd>
  </dl>

  {% include "_bindings_card.html" with context %}

  {% include "_log_pane.html" with context %}

  {% include "_console_pane.html" with context %}
</section>
{% endblock %}
```

The `{% include "_state_pill.html" with context %}` requires the route's context to have `state` set. Update `routes/server.py` to pass `state=server["state"]`:

```python
return templates.TemplateResponse(
    request=request,
    name="server_detail.html",
    context={"version": __version__, "server": server, "state": server["state"]},
)
```

(Read `routes/server.py` first; only the context dict changes.)

- [ ] **Step 4: Append layout rules to `app.css`**

Read the current `src/mcontrol/static/app.css`. Append (do **not** overwrite the existing rules — `tests/test_no_hardcoded_styles.py` continues to gate against drift):

```css
/* ---- Lifecycle row (server detail) --------------------------------- */
.lifecycle-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-6);
  margin: var(--space-6) 0 var(--space-8);
  padding: var(--space-4) var(--space-6);
  background: var(--sub-alt-color);
  border-radius: var(--radius-md);
}

.lifecycle-row__buttons {
  display: flex;
  gap: var(--space-3);
}

.lifecycle-button {
  background: transparent;
  border: 1px solid var(--sub-color);
  border-radius: var(--radius-sm);
  color: var(--text-color);
  padding: var(--space-2) var(--space-5);
  font-size: var(--fs-sm);
  cursor: pointer;
}

.lifecycle-button:hover {
  border-color: var(--main-color);
  color: var(--main-color);
}

/* ---- Bindings card ------------------------------------------------- */
.bindings-card {
  margin-top: var(--space-8);
  padding: var(--space-4) var(--space-6);
  background: var(--sub-alt-color);
  border-radius: var(--radius-md);
}

.bindings-card__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-3);
}

.bindings-card__edit {
  color: var(--main-color);
  text-decoration: none;
  font-size: var(--fs-sm);
}

.bindings-card__body {
  display: grid;
  grid-template-columns: max-content 1fr;
  column-gap: var(--space-6);
  row-gap: var(--space-2);
  margin: var(--space-3) 0 0;
}

.bindings-form {
  display: grid;
  gap: var(--space-3);
  margin-top: var(--space-3);
}

.bindings-form input {
  background: var(--bg-color);
  border: 1px solid var(--sub-color);
  border-radius: var(--radius-sm);
  color: var(--text-color);
  padding: var(--space-2) var(--space-3);
}

.bindings-form__actions {
  display: flex;
  gap: var(--space-3);
  align-items: center;
}

/* ---- Log + console panes ------------------------------------------- */
.log-pane,
.console-pane {
  margin-top: var(--space-8);
  display: grid;
  gap: var(--space-3);
}

.log-pane__stream,
.console-pane__stream {
  background: var(--bg-color);
  border: 1px solid var(--sub-color);
  border-radius: var(--radius-sm);
  color: var(--text-color);
  padding: var(--space-3) var(--space-4);
  height: 16rem;
  overflow-y: auto;
  white-space: pre-wrap;
  margin: 0;
}

.console-pane__input {
  display: flex;
  gap: var(--space-3);
}

.console-pane__input input {
  flex: 1;
  background: var(--bg-color);
  border: 1px solid var(--sub-color);
  border-radius: var(--radius-sm);
  color: var(--text-color);
  padding: var(--space-2) var(--space-3);
}

.console-pane__input button {
  background: transparent;
  border: 1px solid var(--main-color);
  border-radius: var(--radius-sm);
  color: var(--main-color);
  padding: var(--space-2) var(--space-5);
  cursor: pointer;
}
```

- [ ] **Step 5: Run the hardcoded-style guard + full suite**

```bash
uv run pytest tests/test_no_hardcoded_styles.py -v
uv run pytest -v
```

Expected: hardcoded-style guard green; full suite green.

- [ ] **Step 6: Commit**

```bash
git add src/mcontrol/templates/server_detail.html \
        src/mcontrol/static/app.css \
        src/mcontrol/routes/server.py \
        tests/test_server_detail.py
git commit -m "feat(detail): wire lifecycle + log + console + bindings into server detail

Pulls the four new partials into server_detail.html (lifecycle row at
the top, bindings card under the metadata, log + console panes below).
app.css grows token-only layout rules for the new components — guard
remains green."
```

---

# Task 14: Add decision 021 to the register

**Files:**
- Modify: `docs/decisions.md`

- [ ] **Step 1: Add the row to the status table**

Read the current `docs/decisions.md`. Find the status table that ends with row 020. Append a row:

```
| 021 | Per-server `container_name` override + discovery preserves operator edits | Accepted | 2026-04-29 |
```

- [ ] **Step 2: Append the full entry**

At the end of the file, append:

```markdown
## 021. Per-server `container_name` override + discovery preserves operator edits

**Status:** Accepted · 2026-04-29

`app_mcontrol.servers` gains a nullable `container_name text` column. When non-null, lifecycle / logs / RCON code resolves the docker container name via `db.container_name_for(row)` — that helper returns the override when set, otherwise falls back to `servers.name`. Discovery's behaviour is split: new directories get `db.insert_server(name, dir, state)`, and existing rows get `db.update_server_state(name, state)` only — `dir` and `container_name` are **never** overwritten by a discovery scan. State lookup uses the override (so a re-pointed row still shows the correct container's state).

Rejected: storing `container_name` inside `servers.variables` JSONB (a row-level binding is not a runtime variable per decision 013, and JSONB columns are awkward to query). Rejected: writing through `dir` and `container_name` from discovery on every scan (silently undoes operator overrides — exactly the failure mode this decision is preventing). Rejected: deferring the override to a later slice (the underlying contract — discovery does not clobber — has to be true the moment any operator edits a row, and that capability lands this slice with the bindings UI).

Trade-off: discovery becomes two writes (a `get_server` followed by either `insert_server` or `update_server_state`) instead of a single `upsert_server`. At fleet sizes well under 100 servers this overhead is irrelevant, and the alternative — losing operator edits — is the kind of bug that erodes trust in the panel. The `dir` column starts populated on first INSERT only; subsequent scans never touch it, so an operator who repoints `dir` to a different host path will see that override survive every restart of the panel.

This decision pins the contract that future slices (file browser, scaffolding) inherit: any new operator-editable column on `servers` follows the same insert-on-new / state-only-on-existing rule. Discovery's job is to track presence + state, not to be the source of truth for any field an operator can edit.
```

- [ ] **Step 3: Commit**

```bash
git add docs/decisions.md
git commit -m "docs(decisions): 021 — container_name override + discovery preserves operator edits"
```

---

# Task 15: End-to-end verification + PR

**Files:** none modified; verification only.

- [ ] **Step 1: Lint**

```bash
uv run ruff check .
```

Expected: `All checks passed!`

- [ ] **Step 2: Full test suite**

```bash
uv run pytest -v
```

Expected: every test passes. Approximate count after slice 4: ~70 tests across the modules listed in the file structure. Whatever the total, all green.

- [ ] **Step 3: Smoke-build the image (Linux/macOS only)**

```bash
docker compose build app
```

Expected: build succeeds. The new layer for `docker-ce-cli` + `docker-compose-plugin` is large — that's expected.

Skip on Windows dev where `docker compose` may not be available; the bserver post-merge smoke catches Dockerfile issues.

- [ ] **Step 4: Push the branch and open the PR**

```bash
git push -u origin slice4-lifecycle-logs-rcon
gh pr create --title "Slice 4: lifecycle + log SSE + RCON console" --body "$(cat <<'EOF'
## Summary
- HTMX-driven Start / Stop / Restart on `/servers/{name}` (`routes/lifecycle.py`).
- SSE-streamed `docker logs --follow` pane (`routes/logs.py`).
- RCON console — SSE for output + POST for command submission (`routes/console.py`); attaches the panel container to the MC's docker network for the lifetime of the SSE.
- Bespoke ~80-line async Source RCON client (`rcon.py`); no new Python deps.
- Lazy RCON-password generation written to `<dir>/.env` (decision 010).
- Inline bindings edit (`routes/bindings.py`) for per-row `container_name` + `dir` overrides; discovery now preserves operator edits (decision 021).
- Three slice-3 follow-ups folded in: shared `mcontrol.templates`, drop the docker_client N+1 in `container_states_by_name`, add the inner-branch failure test.
- Dockerfile adds Docker CLI + compose v2 plugin (pinned per decision 020); compose mounts widen to `:rw`.

## Pre-merge requirements (operational)
- [ ] `app_mcontrol.servers.container_name` column applied on bserver via `make migrate` in the `supabase-server` repo.

## Test plan
- [ ] `uv run pytest -v` is green (~70 tests).
- [ ] `uv run ruff check .` is green.
- [ ] `tests/test_no_hardcoded_styles.py` is green.
- [ ] On bserver after `docker compose up -d --build`:
  - [ ] `/servers/atm10` renders lifecycle row, log pane, console pane, bindings card.
  - [ ] Click Start on a stopped server → state pill turns to `running` within 30 s.
  - [ ] Log pane streams the startup banner within 5 s of opening.
  - [ ] RCON console accepts `list` and returns the player count.
  - [ ] Click Stop → state pill turns to `exited` within 15 s.
  - [ ] Edit the bindings on a row → discovery's next run preserves the edit.

Refs: docs/decisions.md (006, 008, 010, 011, 016, 020, 021); docs/superpowers/specs/2026-04-29-mcontrol-v1-slice4-design.md.
EOF
)"
```

---

## Subsequent slice stubs

Each stub names the goal and the files added. A full plan for the next slice is written when its predecessor lands.

### Slice 5 — File browser + editor + uploads

Tree view of `<server>/server/`, browser-side editing via Monaco from CDN, single-file upload (server jar) and multi-file upload (mods). Path-traversal guards in `filesystem.py` are critical — every path must be normalised and asserted to live under `SERVER_BASE_PATH`. Adds `routes/files.py`, `filesystem.py`. Slice-4's bindings UI is already in place to repoint `dir` if a server moves on disk.

### Slice 6 — New-server scaffolding flow

Form → generated `docker-compose.yml`, `Dockerfile`, `entrypoint.sh`, `start_server.sh`, `.env` (decisions 001, 008, 010, 012, 013). Adds `templates_gen.py`, `routes/new_server.py`, server-template j2 files. May add an `rcon_port` schema field if per-server RCON port needs to vary.

### Slice 7 — Whitelist + ops UI

Per decision 018: RCON when running, file edits when offline, file edit + reload for granular op levels. Adds `routes/whitelist_ops.py`. Slice 4's RCON client is the foundation.

### Slice 8 — itzg → temurin migration for `atm10` + `monifactory`

One-time UI button (or CLI subcommand) per decision 014: rewrite Dockerfile base to `eclipse-temurin:21-jre`, rebuild image. World data untouched. `kobra_kollektivet` is unaffected.

---

## Self-review

**Spec coverage:** every requirement in `docs/superpowers/specs/2026-04-29-mcontrol-v1-slice4-design.md` is implemented:
- Lifecycle (Start / Stop / Restart) — Task 9.
- SSE log stream — Task 10.
- RCON console (SSE + POST) — Task 11.
- Bespoke async RCON — Task 8.
- Lazy RCON password generation + `.env` write — Task 5 + Task 9.
- Bindings edit UI + schema column + discovery cleanup — Task 3 + Task 4 + Task 12 + P2.
- Network attach for RCON — Task 7 + Task 11.
- Mount widening + Dockerfile additions — Task 1.
- Slice-3 follow-ups (templates module, drop N+1, inner-branch test) — Task 2.
- Decision 021 added — Task 14.

**Placeholder scan:** every code block is full and copy-pasteable. The only `<…>` substitution is `<timestamp>` for the migration filename, which is generated at execution time via `date +%Y%m%d%H%M%S`. The Docker CLI / compose plugin pins are concrete (`5:27.4.0-1~debian.12~bookworm`, `2.31.0-1~debian.12~bookworm`); if they fail apt resolution at build time, Task 1's note tells the implementer to bump and follow up.

**Type consistency:**
- `db.container_name_for(row)` is the single resolution helper used by lifecycle, logs, console, and discovery. Same signature everywhere: takes a row dict, returns a string.
- `_RconConnection.run(command: str) -> str` is what the console uses; tests' `_FakeRconConnection.run` matches.
- `docker_client.start/stop/restart(container_name: str) -> None` are uniform.
- `compose_runner.up_force_recreate(server_dir: Path) -> None` raises `ComposeError`.
- `env_writer.write_rcon_password(env_path: Path, password: str)` and `read_rcon_password(env_path: Path) -> str | None`.
- `passwords.generate() -> str`.

**Karpathy guidelines applied:**
- No new Python deps. RCON is bespoke; everything else uses what's already there.
- No "rotate password" button. Lazy generation only.
- No state-subscription SSE. Blocking lifecycle is enough until proven slow.
- No connection pool for RCON. Hold the SSE-lifetime connection; nothing more.
- No retries / backoff. Single-user; user-driven retry is fine.
- Bindings UI is two fields and one form, not a settings framework.
- Discovery cleanup is surgical — replaces one upsert with two narrower writes; doesn't refactor discovery's structure.
- `compose_runner` is a 30-line subprocess wrapper, not a compose-file parser.
- Image bloat is acknowledged, not glossed over (~50 MB for Docker CLI + compose plugin).

**Verifiable success criteria:** Task 15 lists them as the PR's test plan checklist; pre-merge gates the schema migration explicitly; the live-deploy smoke walks the happy path through every new surface.

**Parallelism note:** Tasks 9, 10, 11, and 12 are independent of each other once Tasks 1-8 are done — they touch separate route modules and separate templates. If using `superpowers:dispatching-parallel-agents`, dispatch them concurrently after Task 8 completes. Task 13 (template wiring) depends on all four.
