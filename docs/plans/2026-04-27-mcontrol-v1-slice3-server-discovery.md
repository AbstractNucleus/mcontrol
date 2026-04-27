# mcontrol v1 — Slice 3: Server Discovery + Read-only Server List Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Walk `SERVER_BASE_PATH` on startup, register each subdirectory as a row in `app_mcontrol.servers` (refreshing its container state from Docker), and replace the home empty-state with a read-only list of those rows. Add a per-server detail page that renders the row's stored fields. No lifecycle controls, no log streaming, no RCON, no file UI — those are slices 4+.

**Architecture:** Three small pure-ish modules — `db.py` (synchronous supabase-py wrapper, scoped to `app_mcontrol.servers`, constructed once and cached at module level), `docker_client.py` (async aiodocker wrapper exposing one function: `container_states_by_name()`), and `discovery.py` (walks the base path, joins fs ⇄ docker, upserts each row). Discovery is driven by FastAPI's lifespan context manager so it runs once per app start; tests don't trigger it because `httpx.AsyncClient` with `ASGITransport` doesn't run lifespans by default. Routes (`/`, `/servers/{name}`) read straight from `db.py`; the home page conditionally renders a list-of-servers OR the existing empty state. All UI consumes only `tokens.css` variables and the existing `app.css` layout shell — `tests/test_no_hardcoded_styles.py` continues to gate against drift.

**Tech Stack:** Python 3.12, FastAPI, Jinja2 (existing); add `supabase>=2.9` and `aiodocker>=0.24` as runtime deps. Tests use `monkeypatch` to replace the `db.py` wrappers and the `aiodocker.Docker` constructor — no real Supabase or Docker calls run in CI.

---

## Scope of this plan

This plan delivers **Slice 3 of v1 only — server discovery and a read-only list**. It assumes slice 2 (the `app_mcontrol` schema + PostgREST exposure) has landed; without that, the home page will 500 on first DB call. Subsequent slices each get their own plan after this one lands:

| Slice | Scope | Plan |
|---|---|---|
| 4 | Start/Stop/Restart + log SSE + RCON console | TBD |
| 5 | File browser + editor + jar/mod uploads | TBD |
| 6 | New-server scaffolding flow | TBD |
| 7 | Whitelist + ops UI | TBD |
| 8 | itzg → temurin migration for `atm10` + `monifactory` | TBD |

## Decisions register references

This slice acts on:
- **006** Direct `/var/run/docker.sock` mount (this slice mounts it read-only — slice 4 switches to read-write for lifecycle ops)
- **007** Shared Supabase, schema `app_mcontrol`
- **008** Bind mounts at `~abstract/servers/minecraft/<name>/` (this is the path the discovery routine walks)
- **011** `SERVICE_ROLE_KEY` server-side; no app-level user
- **013** Bespoke variable schema in `servers.variables` JSONB (this slice reads it and renders it; populates writes are slice 6)
- **016** Backend stack: FastAPI + Jinja + HTMX (HTMX still unused this slice)

Deferred: 009, 010 (RCON column exists but isn't generated/written this slice), 012, 014, 015, 017, 018.

## Assumptions (surfaced, not buried)

1. **Slice 2 has landed.** `app_mcontrol.servers` exists, RLS is on with no policies, and `app_mcontrol` is in `PGRST_DB_SCHEMAS`. Without this, every db call in slice 3 returns `Schema 'app_mcontrol' does not exist or is not exposed`. The smoke test in Task 11 verifies live against the deployed Supabase before declaring success.
2. **Discovery runs once at app startup, in a FastAPI lifespan handler.** It is **not** re-triggered on home requests, on a timer, or on a button. Operators who add a directory after start must restart the `app` container (`docker compose restart app`) to see it. A "Rescan" button is a slice 4+ follow-up; deferring it keeps slice 3 small.
3. **Container name == directory name.** When discovery sees `<base>/atm10/`, it queries Docker for a container named `atm10`. This matches existing bserver naming (verified in the bserver inventory). If a future server uses a different container name, decision 008's bind-mount layout still pins the directory name as canonical, so this assumption holds for v1.
4. **The supabase-py SDK is synchronous.** Calling it from inside an async handler blocks the event loop briefly. For a single-user tailnet panel with infrequent requests, this is fine; if it ever bottlenecks (multi-tab usage, slow Postgres), wrap individual calls in `asyncio.to_thread`. The plan does **not** preemptively async-wrap — that's the kind of thing karpathy-guidelines tells you to skip until you have a reason.
5. **Docker access on Windows dev.** aiodocker can connect via `DOCKER_HOST=tcp://localhost:2375` (Docker Desktop with that exposure enabled) but the more common Windows-dev path is "no docker, accept that discovery returns `state="unknown"` for everything." The discovery routine catches connection failures from `aiodocker` and falls back to an empty state map (every dir gets `state="unknown"`), so the app still boots and renders. The single source of truth for the dev case is the test suite — Windows-only manual testing is not a release gate.
6. **The docker socket mount on the tracked `docker-compose.yml`.** Slice 1's compose does not mount `/var/run/docker.sock`. This slice adds it as a read-only bind on the `app` service. Bserver's `docker-compose.override.yml` (gitignored) is unaffected — overrides are per-service stanzas; the new `volumes:` line in the tracked file merges with the override unless the override explicitly nulls it. Verify on first deploy.
7. **Discovery grants from the migration.** Slice 2's migration grants `service_role` `ALL` on `app_mcontrol.servers`. The supabase-py client uses `SERVICE_ROLE_KEY`, which PostgREST maps to the `service_role` Postgres role, which bypasses RLS — so the upsert in discovery succeeds without policies. If that test ever fails with `permission denied`, the slice-2 grant is missing.
8. **A row's `state` is "last seen at startup."** The home page may show stale state if a container exited after discovery ran. This is acceptable for a read-only slice; slice 4 adds live refresh via the lifecycle controls. The UI does not advertise the staleness explicitly — keeping it honest can be a slice-4 addition (e.g., showing `updated_at` or wiring a poll).

## File structure for v1 (slice 3 touches files marked **§3**)

```
mcontrol/
├── pyproject.toml                               §3 (modify: deps)
├── uv.lock                                      §3 (regenerate)
├── docker-compose.yml                           §3 (modify: socket mount)
├── src/
│   └── mcontrol/
│       ├── __init__.py                          (existing)
│       ├── main.py                              §3 (modify: lifespan)
│       ├── settings.py                          §3 (modify: docker_host)
│       ├── db.py                                §3 (new)
│       ├── docker_client.py                     §3 (new)
│       ├── discovery.py                         §3 (new)
│       ├── routes/
│       │   ├── __init__.py                      (existing)
│       │   ├── home.py                          §3 (modify: list servers)
│       │   └── server.py                        §3 (new)
│       ├── templates/
│       │   ├── base.html                        (existing)
│       │   ├── home.html                        §3 (modify: server list block)
│       │   └── server_detail.html               §3 (new)
│       └── static/
│           ├── tokens.css                       (existing)
│           └── app.css                          §3 (modify: server-list styles)
└── tests/
    ├── conftest.py                              §3 (modify: fake DB fixture)
    ├── test_settings.py                         §3 (modify: docker_host default)
    ├── test_db.py                               §3 (new)
    ├── test_docker_client.py                    §3 (new)
    ├── test_discovery.py                        §3 (new)
    ├── test_home.py                             §3 (modify: list rendering)
    ├── test_server_detail.py                    §3 (new)
    ├── test_healthz.py                          (existing)
    ├── test_static.py                           (existing)
    └── test_no_hardcoded_styles.py              (existing)
```

---

# Pre-flight

- [ ] **P1: Create a feature branch off `main`**

```bash
git checkout main
git pull --ff-only
git checkout -b slice3-server-discovery
git status
```

Expected: on `slice3-server-discovery`, `nothing to commit, working tree clean`.

- [ ] **P2: Confirm slice 2 has landed against the deployed Supabase**

Set `SR_KEY` to the service-role key from `bserver:~/repos/mcontrol/.env` (or `bserver:~/repos/supabase-server/.env`):

```bash
curl -fsS \
  -H "apikey: $SR_KEY" \
  -H "Authorization: Bearer $SR_KEY" \
  -H "Accept-Profile: app_mcontrol" \
  'https://api.noelkleen.com/rest/v1/servers?select=name&limit=1'
```

Expected: `[]` or a small JSON array. If you get `Schema 'app_mcontrol' does not exist or is not exposed` or a 404, slice 2 is incomplete — pause this plan and finish slice 2 first.

- [ ] **P3: Confirm `uv` and tests are green at the slice-1 baseline**

Run: `uv run pytest -v`
Expected: the slice-1 suite passes (settings, healthz, static, home, no-hardcoded-styles — all green).

---

# Task 1: Add `supabase` and `aiodocker` dependencies

**Files:**
- Modify: `pyproject.toml`
- Regenerate: `uv.lock`

- [ ] **Step 1: Add the deps**

Edit `pyproject.toml`, replacing the `dependencies = [...]` block with:

```toml
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "jinja2>=3.1",
    "pydantic>=2.9",
    "pydantic-settings>=2.6",
    "supabase>=2.9",
    "aiodocker>=0.24",
]
```

- [ ] **Step 2: Resolve and lock**

Run: `uv sync`
Expected: `uv.lock` regenerates, `Resolved N packages` and `Installed N packages` (N grows by ~10–20 to cover supabase + aiodocker transitive deps). Exit 0.

- [ ] **Step 3: Smoke-import the new deps**

Run: `uv run python -c "import supabase, aiodocker; print('ok')"`
Expected: `ok`.

- [ ] **Step 4: Re-run the existing test suite as a regression check**

Run: `uv run pytest -v`
Expected: same passes as P3 (no test added or modified yet).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add supabase + aiodocker deps for slice 3"
```

---

# Task 2: Add `docker_host` setting

**Files:**
- Modify: `src/mcontrol/settings.py`
- Modify: `tests/test_settings.py`

- [ ] **Step 1: Write the failing test**

Edit `tests/test_settings.py` — add this test below the two existing tests:

```python
def test_settings_docker_host_default(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://api.noelkleen.com")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")
    monkeypatch.setenv("SERVER_BASE_PATH", "/home/abstract/servers/minecraft")
    monkeypatch.delenv("DOCKER_HOST", raising=False)

    settings = Settings()

    assert settings.docker_host == "unix:///var/run/docker.sock"


def test_settings_docker_host_override(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://api.noelkleen.com")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")
    monkeypatch.setenv("SERVER_BASE_PATH", "/home/abstract/servers/minecraft")
    monkeypatch.setenv("DOCKER_HOST", "tcp://localhost:2375")

    settings = Settings()

    assert settings.docker_host == "tcp://localhost:2375"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_settings.py -v`
Expected: 2 new tests FAIL with `AttributeError: 'Settings' object has no attribute 'docker_host'`.

- [ ] **Step 3: Add the field**

Edit `src/mcontrol/settings.py` — add `docker_host` to the model:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    supabase_url: str
    supabase_service_role_key: str
    server_base_path: str
    docker_host: str = "unix:///var/run/docker.sock"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_settings.py -v`
Expected: 4 passed (2 original + 2 new).

- [ ] **Step 5: Commit**

```bash
git add src/mcontrol/settings.py tests/test_settings.py
git commit -m "feat(settings): docker_host with unix-socket default"
```

---

# Task 3: `db.py` — supabase-py wrapper for `app_mcontrol.servers`

**Files:**
- Create: `src/mcontrol/db.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_db.py`:

```python
from unittest.mock import MagicMock

import pytest

from mcontrol import db


@pytest.fixture(autouse=True)
def _reset_client_singleton(monkeypatch):
    """Each test starts with a fresh _client_singleton."""
    monkeypatch.setattr(db, "_client_singleton", None)


def _fake_supabase_client():
    """Build a fake supabase client whose .schema().table() chain we can introspect."""
    client = MagicMock(name="supabase_client")
    table = client.schema.return_value.table.return_value
    return client, table


def test_client_constructed_with_settings(env, monkeypatch):
    captured = {}

    def fake_create_client(url, key):
        captured["url"] = url
        captured["key"] = key
        return MagicMock()

    monkeypatch.setattr(db, "create_client", fake_create_client)

    db._client()

    assert captured == {"url": "https://api.noelkleen.com", "key": "test-key"}


def test_client_is_cached(env, monkeypatch):
    calls = {"n": 0}

    def fake_create_client(url, key):
        calls["n"] += 1
        return MagicMock()

    monkeypatch.setattr(db, "create_client", fake_create_client)

    a = db._client()
    b = db._client()

    assert a is b
    assert calls["n"] == 1


def test_table_targets_app_mcontrol_servers(env, monkeypatch):
    client, _ = _fake_supabase_client()
    monkeypatch.setattr(db, "_client_singleton", client)

    db._table()

    client.schema.assert_called_once_with("app_mcontrol")
    client.schema.return_value.table.assert_called_once_with("servers")


def test_list_servers_orders_by_name(env, monkeypatch):
    client, table = _fake_supabase_client()
    monkeypatch.setattr(db, "_client_singleton", client)
    table.select.return_value.order.return_value.execute.return_value.data = [
        {"name": "atm10"},
        {"name": "monifactory"},
    ]

    rows = db.list_servers()

    table.select.assert_called_once_with("*")
    table.select.return_value.order.assert_called_once_with("name")
    assert rows == [{"name": "atm10"}, {"name": "monifactory"}]


def test_get_server_returns_first_row(env, monkeypatch):
    client, table = _fake_supabase_client()
    monkeypatch.setattr(db, "_client_singleton", client)
    table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"name": "atm10", "state": "running"},
    ]

    row = db.get_server("atm10")

    table.select.return_value.eq.assert_called_once_with("name", "atm10")
    assert row == {"name": "atm10", "state": "running"}


def test_get_server_returns_none_when_missing(env, monkeypatch):
    client, table = _fake_supabase_client()
    monkeypatch.setattr(db, "_client_singleton", client)
    table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []

    assert db.get_server("nope") is None


def test_upsert_server_uses_name_as_conflict_key(env, monkeypatch):
    client, table = _fake_supabase_client()
    monkeypatch.setattr(db, "_client_singleton", client)

    db.upsert_server(name="atm10", dir="/srv/atm10", state="running")

    args, kwargs = table.upsert.call_args
    payload = args[0]
    assert payload == {"name": "atm10", "dir": "/srv/atm10", "state": "running"}
    assert kwargs == {"on_conflict": "name"}
    table.upsert.return_value.execute.assert_called_once_with()
```

(`env` is the existing fixture from `tests/conftest.py` — sets `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SERVER_BASE_PATH`.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_db.py -v`
Expected: every test FAILS with `ModuleNotFoundError: No module named 'mcontrol.db'`.

- [ ] **Step 3: Implement `db.py`**

Create `src/mcontrol/db.py`:

```python
"""Thin wrapper over supabase-py, scoped to app_mcontrol.servers.

All callers go through list_servers / get_server / upsert_server. The
underlying client is constructed lazily on first use and cached for the
lifetime of the process.
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


def upsert_server(*, name: str, dir: str, state: str) -> None:
    _table().upsert(
        {"name": name, "dir": dir, "state": state},
        on_conflict="name",
    ).execute()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_db.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/mcontrol/db.py tests/test_db.py
git commit -m "feat(db): supabase-py wrapper for app_mcontrol.servers"
```

---

# Task 4: `docker_client.py` — async wrapper around aiodocker

**Files:**
- Create: `src/mcontrol/docker_client.py`
- Create: `tests/test_docker_client.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_docker_client.py`:

```python
from unittest.mock import AsyncMock, MagicMock

import pytest

from mcontrol import docker_client


class _FakeContainer:
    def __init__(self, name: str, status: str):
        self._name = name
        self._status = status

    async def show(self) -> dict:
        return {"Name": f"/{self._name}", "State": {"Status": self._status}}


class _FakeContainers:
    def __init__(self, containers: list[_FakeContainer]):
        self._containers = containers

    async def list(self, all: bool = False) -> list[_FakeContainer]:  # noqa: A002
        assert all is True, "discovery must list ALL containers, including stopped"
        return self._containers


class _FakeDocker:
    def __init__(self, containers: list[_FakeContainer]):
        self.containers = _FakeContainers(containers)
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_docker(monkeypatch):
    containers: list[_FakeContainer] = []

    def factory(*, url: str | None = None) -> _FakeDocker:
        return _FakeDocker(containers)

    monkeypatch.setattr(docker_client.aiodocker, "Docker", factory)
    return containers


async def test_container_states_by_name_returns_mapping(env, fake_docker):
    fake_docker.append(_FakeContainer("atm10", "running"))
    fake_docker.append(_FakeContainer("monifactory", "exited"))

    states = await docker_client.container_states_by_name()

    assert states == {"atm10": "running", "monifactory": "exited"}


async def test_container_states_strips_leading_slash(env, fake_docker):
    fake_docker.append(_FakeContainer("kobra_kollektivet", "created"))

    states = await docker_client.container_states_by_name()

    assert states == {"kobra_kollektivet": "created"}


async def test_container_states_returns_empty_when_docker_unreachable(env, monkeypatch):
    class _Boom:
        def __init__(self, *_, **__):
            raise RuntimeError("docker daemon is sulking")

    monkeypatch.setattr(docker_client.aiodocker, "Docker", _Boom)

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

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_docker_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mcontrol.docker_client'`.

- [ ] **Step 3: Implement `docker_client.py`**

Create `src/mcontrol/docker_client.py`:

```python
"""Thin async wrapper around aiodocker for container-state lookups.

Slice 3 only needs to enumerate container names + statuses. Slice 4 will
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
            info = await c.show()
            name = info["Name"].lstrip("/")
            states[name] = info["State"]["Status"]
        return states
    except Exception:
        return {}
    finally:
        with suppress(Exception):
            await docker.close()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_docker_client.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/mcontrol/docker_client.py tests/test_docker_client.py
git commit -m "feat(docker): aiodocker wrapper for container state lookup"
```

---

# Task 5: `discovery.py` — walk + upsert

**Files:**
- Create: `src/mcontrol/discovery.py`
- Create: `tests/test_discovery.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_discovery.py`:

```python
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from mcontrol import discovery


@pytest.fixture
def upserts(monkeypatch):
    calls: list[dict] = []

    def fake_upsert_server(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(discovery.db, "upsert_server", fake_upsert_server)
    return calls


def _make_dirs(base: Path, names: list[str]) -> None:
    for n in names:
        (base / n).mkdir(parents=True, exist_ok=True)


async def test_run_discovery_skips_when_base_path_missing(tmp_path, upserts, monkeypatch):
    monkeypatch.setattr(
        discovery.docker_client,
        "container_states_by_name",
        AsyncMock(return_value={}),
    )

    count = await discovery.run_discovery(tmp_path / "does-not-exist")

    assert count == 0
    assert upserts == []


async def test_run_discovery_returns_zero_when_no_subdirs(tmp_path, upserts, monkeypatch):
    monkeypatch.setattr(
        discovery.docker_client,
        "container_states_by_name",
        AsyncMock(return_value={}),
    )

    count = await discovery.run_discovery(tmp_path)

    assert count == 0
    assert upserts == []


async def test_run_discovery_upserts_one_row_per_subdir(tmp_path, upserts, monkeypatch):
    _make_dirs(tmp_path, ["atm10", "monifactory", "kobra_kollektivet"])
    monkeypatch.setattr(
        discovery.docker_client,
        "container_states_by_name",
        AsyncMock(return_value={"atm10": "running", "monifactory": "exited"}),
    )

    count = await discovery.run_discovery(tmp_path)

    assert count == 3
    by_name = {u["name"]: u for u in upserts}
    assert by_name["atm10"] == {
        "name": "atm10",
        "dir": str(tmp_path / "atm10"),
        "state": "running",
    }
    assert by_name["monifactory"]["state"] == "exited"
    assert by_name["kobra_kollektivet"]["state"] == "unknown"


async def test_run_discovery_ignores_non_directories(tmp_path, upserts, monkeypatch):
    _make_dirs(tmp_path, ["atm10"])
    (tmp_path / "stray-file.txt").write_text("ignore me")
    monkeypatch.setattr(
        discovery.docker_client,
        "container_states_by_name",
        AsyncMock(return_value={}),
    )

    count = await discovery.run_discovery(tmp_path)

    assert count == 1
    assert [u["name"] for u in upserts] == ["atm10"]


async def test_run_discovery_processes_dirs_in_sorted_order(tmp_path, upserts, monkeypatch):
    _make_dirs(tmp_path, ["zeta", "alpha", "mu"])
    monkeypatch.setattr(
        discovery.docker_client,
        "container_states_by_name",
        AsyncMock(return_value={}),
    )

    await discovery.run_discovery(tmp_path)

    assert [u["name"] for u in upserts] == ["alpha", "mu", "zeta"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_discovery.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mcontrol.discovery'`.

- [ ] **Step 3: Implement `discovery.py`**

Create `src/mcontrol/discovery.py`:

```python
"""Server discovery — walks SERVER_BASE_PATH and registers each subdirectory
in app_mcontrol.servers, refreshing its state from Docker.

Idempotent. Designed to run once on app startup via FastAPI's lifespan
context manager. A future slice may add a "Rescan" button.
"""

from pathlib import Path

from mcontrol import db, docker_client


async def run_discovery(base_path: Path) -> int:
    """Walk base_path, upsert each subdirectory. Returns count of dirs seen.

    If base_path doesn't exist, returns 0 without touching the DB. If Docker
    is unreachable, every dir gets state="unknown" via the empty mapping
    returned from docker_client.
    """
    if not base_path.exists():
        return 0

    states = await docker_client.container_states_by_name()
    count = 0
    for entry in sorted(base_path.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue
        db.upsert_server(
            name=entry.name,
            dir=str(entry),
            state=states.get(entry.name, "unknown"),
        )
        count += 1
    return count
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_discovery.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/mcontrol/discovery.py tests/test_discovery.py
git commit -m "feat(discovery): walk SERVER_BASE_PATH and upsert servers"
```

---

# Task 6: Wire discovery into FastAPI's lifespan

**Files:**
- Modify: `src/mcontrol/main.py`
- Create: `tests/test_lifespan.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_lifespan.py`:

```python
from unittest.mock import AsyncMock

from httpx import ASGITransport, AsyncClient


async def test_lifespan_runs_discovery_with_settings_path(env, monkeypatch, tmp_path):
    monkeypatch.setenv("SERVER_BASE_PATH", str(tmp_path))

    captured = {}
    fake_run = AsyncMock(return_value=0)

    async def wrapper(base_path):
        captured["base_path"] = base_path
        return await fake_run(base_path)

    from mcontrol import discovery, main

    monkeypatch.setattr(discovery, "run_discovery", wrapper)

    app = main.create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Trigger lifespan startup explicitly via the test transport.
        async with app.router.lifespan_context(app):
            await ac.get("/healthz")

    assert captured["base_path"] == tmp_path


async def test_lifespan_does_not_block_startup_on_discovery_failure(env, monkeypatch, tmp_path):
    monkeypatch.setenv("SERVER_BASE_PATH", str(tmp_path))

    async def boom(_):
        raise RuntimeError("supabase died")

    from mcontrol import discovery, main

    monkeypatch.setattr(discovery, "run_discovery", boom)

    app = main.create_app()
    # Entering and exiting the lifespan should NOT raise.
    async with app.router.lifespan_context(app):
        pass
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_lifespan.py -v`
Expected: FAIL — the first test fails because lifespan doesn't call discovery; the second may also fail or error depending on the slice-1 baseline.

- [ ] **Step 3: Add the lifespan to `main.py`**

Edit `src/mcontrol/main.py` — replace the file with:

```python
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from mcontrol import discovery
from mcontrol.routes import home
from mcontrol.settings import Settings

STATIC_DIR = Path(__file__).parent / "static"

logger = logging.getLogger("mcontrol")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    base_path = Path(settings.server_base_path)
    try:
        count = await discovery.run_discovery(base_path)
        logger.info("discovery: %d server dir(s) seen under %s", count, base_path)
    except Exception:
        # Discovery must never block the app from coming up — the home page
        # surfaces an empty state and the operator can investigate from there.
        logger.exception("discovery failed; continuing without it")
    yield


def create_app() -> FastAPI:
    settings = Settings()
    app = FastAPI(title="mcontrol", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(home.router)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_lifespan.py -v`
Expected: 2 passed.

- [ ] **Step 5: Confirm the existing test suite still passes**

Run: `uv run pytest -v`
Expected: every prior test still passes (tests use `AsyncClient` without `LifespanManager`, so they don't trigger the lifespan and don't hit `discovery.run_discovery`).

- [ ] **Step 6: Commit**

```bash
git add src/mcontrol/main.py tests/test_lifespan.py
git commit -m "feat(main): run discovery in fastapi lifespan"
```

---

# Task 7: Replace home empty-state with a real server list

**Files:**
- Modify: `src/mcontrol/routes/home.py`
- Modify: `src/mcontrol/templates/home.html`
- Modify: `tests/test_home.py`

- [ ] **Step 1: Update the failing tests**

Replace the contents of `tests/test_home.py` with:

```python
import pytest


@pytest.fixture
def fake_servers(monkeypatch):
    rows: list[dict] = []

    def fake_list_servers():
        return rows

    from mcontrol import db

    monkeypatch.setattr(db, "list_servers", fake_list_servers)
    return rows


async def test_home_renders_wordmark(client, fake_servers):
    response = await client.get("/")

    assert response.status_code == 200
    body = response.text
    assert "mcontrol" in body
    assert "/static/tokens.css" in body
    assert "/static/app.css" in body


async def test_home_shows_empty_state_when_no_servers(client, fake_servers):
    response = await client.get("/")

    assert response.status_code == 200
    assert "No servers yet" in response.text


async def test_home_lists_servers_when_present(client, fake_servers):
    fake_servers.append({"name": "atm10", "state": "running"})
    fake_servers.append({"name": "monifactory", "state": "exited"})

    response = await client.get("/")

    assert response.status_code == 200
    body = response.text
    assert "atm10" in body
    assert "monifactory" in body
    assert "running" in body
    assert "exited" in body
    assert "No servers yet" not in body


async def test_home_links_each_server_to_detail_page(client, fake_servers):
    fake_servers.append({"name": "atm10", "state": "running"})

    response = await client.get("/")

    assert response.status_code == 200
    assert 'href="/servers/atm10"' in response.text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_home.py -v`
Expected: at least the new server-listing tests FAIL (the home route still returns the static empty state).

- [ ] **Step 3: Update the home route**

Replace `src/mcontrol/routes/home.py` with:

```python
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from mcontrol import __version__, db

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

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

- [ ] **Step 4: Update the home template**

Replace `src/mcontrol/templates/home.html` with:

```html
{% extends "base.html" %}

{% block title %}mcontrol — servers{% endblock %}

{% block main %}
<section>
  <p class="t-eyebrow">Servers</p>
  {% if servers %}
    <ul class="server-list">
      {% for server in servers %}
        <li class="server-card">
          <a class="server-card__name" href="/servers/{{ server.name }}">{{ server.name }}</a>
          <span class="server-card__state server-card__state--{{ server.state }}">{{ server.state }}</span>
        </li>
      {% endfor %}
    </ul>
  {% else %}
    <div class="card">
      <p class="t-body">No servers yet — drop a directory into <code>{{ "{SERVER_BASE_PATH}" }}</code> and restart the panel.</p>
    </div>
  {% endif %}
</section>
{% endblock %}
```

(The `{{ "{SERVER_BASE_PATH}" }}` is intentional: render the literal string `{SERVER_BASE_PATH}` in the empty-state copy without injecting the actual path.)

- [ ] **Step 5: Run the home tests to verify they pass**

Run: `uv run pytest tests/test_home.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add src/mcontrol/routes/home.py src/mcontrol/templates/home.html tests/test_home.py
git commit -m "feat(home): render real server list, fall back to empty state"
```

---

# Task 8: Per-server detail page

**Files:**
- Create: `src/mcontrol/routes/server.py`
- Create: `src/mcontrol/templates/server_detail.html`
- Modify: `src/mcontrol/main.py` (register the router)
- Create: `tests/test_server_detail.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_server_detail.py`:

```python
import pytest


@pytest.fixture
def fake_get_server(monkeypatch):
    rows: dict[str, dict | None] = {}

    def fake(name):
        return rows.get(name)

    from mcontrol import db

    monkeypatch.setattr(db, "get_server", fake)
    return rows


async def test_server_detail_returns_404_when_unknown(client, fake_get_server):
    response = await client.get("/servers/does-not-exist")

    assert response.status_code == 404


async def test_server_detail_renders_known_server(client, fake_get_server):
    fake_get_server["atm10"] = {
        "name": "atm10",
        "dir": "/home/abstract/servers/minecraft/atm10",
        "image_base": "eclipse-temurin:21-jre",
        "state": "running",
        "variables": {"memory_budget_gb": 12, "port": 25565},
        "created_at": "2026-04-27T10:00:00Z",
        "updated_at": "2026-04-27T10:00:00Z",
    }

    response = await client.get("/servers/atm10")

    assert response.status_code == 200
    body = response.text
    assert "atm10" in body
    assert "/home/abstract/servers/minecraft/atm10" in body
    assert "eclipse-temurin:21-jre" in body
    assert "running" in body
    # variables are surfaced verbatim
    assert "memory_budget_gb" in body
    assert "25565" in body


async def test_server_detail_handles_null_image_base(client, fake_get_server):
    fake_get_server["fresh"] = {
        "name": "fresh",
        "dir": "/srv/fresh",
        "image_base": None,
        "state": "unknown",
        "variables": {},
        "created_at": "2026-04-27T10:00:00Z",
        "updated_at": "2026-04-27T10:00:00Z",
    }

    response = await client.get("/servers/fresh")

    assert response.status_code == 200
    # Empty image_base renders as a placeholder, not the literal "None".
    assert "None" not in response.text or "image_base" not in response.text
    assert "fresh" in response.text


async def test_server_detail_links_back_to_home(client, fake_get_server):
    fake_get_server["atm10"] = {
        "name": "atm10",
        "dir": "/srv/atm10",
        "image_base": None,
        "state": "running",
        "variables": {},
        "created_at": "2026-04-27T10:00:00Z",
        "updated_at": "2026-04-27T10:00:00Z",
    }

    response = await client.get("/servers/atm10")

    assert 'href="/"' in response.text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_server_detail.py -v`
Expected: every test FAILS with status 404 (route doesn't exist yet).

- [ ] **Step 3: Implement the route**

Create `src/mcontrol/routes/server.py`:

```python
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from mcontrol import __version__, db

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

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

- [ ] **Step 4: Create the detail template**

Create `src/mcontrol/templates/server_detail.html`:

```html
{% extends "base.html" %}

{% block title %}{{ server.name }} — mcontrol{% endblock %}

{% block main %}
<section>
  <p class="t-eyebrow"><a href="/">← all servers</a></p>
  <h2 class="t-h3">{{ server.name }}</h2>

  <dl class="server-detail">
    <dt class="t-caption">state</dt>
    <dd class="server-detail__state server-detail__state--{{ server.state }}">{{ server.state }}</dd>

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
</section>
{% endblock %}
```

- [ ] **Step 5: Register the router in `main.py`**

Edit `src/mcontrol/main.py` — change the imports and the `create_app` body:

```python
from mcontrol.routes import home, server
```

and

```python
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(home.router)
    app.include_router(server.router)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_server_detail.py -v`
Expected: 4 passed.

- [ ] **Step 7: Run the full suite as a regression check**

Run: `uv run pytest -v`
Expected: every test passes. The `test_no_hardcoded_styles.py` guard does **not** scan templates — only `app.css` — so the new template's color classes (which all reference tokens via `app.css`) are fine here; the guard's job is to keep `app.css` itself clean.

- [ ] **Step 8: Commit**

```bash
git add src/mcontrol/routes/server.py src/mcontrol/templates/server_detail.html src/mcontrol/main.py tests/test_server_detail.py
git commit -m "feat(server): per-server detail page (read-only)"
```

---

# Task 9: CSS for server list and detail

**Files:**
- Modify: `src/mcontrol/static/app.css`

`app.css` is the layout-only sheet. **No `font-family` and no hex colors are allowed** — `tests/test_no_hardcoded_styles.py` enforces this. All visual tokens come from `var(--*)` defined in `tokens.css`.

- [ ] **Step 1: Append the new layout rules**

Edit `src/mcontrol/static/app.css` — append (do not overwrite the existing rules):

```css
/* ---- Server list (home page) ----------------------------------------- */
.server-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--space-3);
}

.server-card {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-6);
  background: var(--sub-alt-color);
  border-radius: var(--radius-md);
}

.server-card__name {
  color: var(--text-color);
  text-decoration: none;
  font-size: var(--fs-md);
}

.server-card__name:hover {
  color: var(--main-color);
}

.server-card__state {
  font-size: var(--fs-xs);
  color: var(--sub-color);
}

.server-card__state--running {
  color: var(--success-color);
}

.server-card__state--exited,
.server-card__state--dead {
  color: var(--error-color);
}

.server-card__state--restarting,
.server-card__state--paused {
  color: var(--main-color);
}

/* ---- Server detail page --------------------------------------------- */
.server-detail {
  display: grid;
  grid-template-columns: max-content 1fr;
  column-gap: var(--space-6);
  row-gap: var(--space-2);
  margin: var(--space-6) 0 0;
}

.server-detail dt {
  margin: 0;
  color: var(--sub-color);
}

.server-detail dd {
  margin: 0;
}

.server-detail__state--running { color: var(--success-color); }
.server-detail__state--exited,
.server-detail__state--dead { color: var(--error-color); }

.kv-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--space-1);
}

.t-muted {
  color: var(--sub-color);
}
```

- [ ] **Step 2: Run the hardcoded-style guard**

Run: `uv run pytest tests/test_no_hardcoded_styles.py -v`
Expected: 2 passed. If any test fails, you introduced either a hex color or a `font-family` declaration — fix and re-run.

- [ ] **Step 3: Visual sanity check (Linux dev or bserver)**

Run: `SUPABASE_URL=https://api.noelkleen.com SUPABASE_SERVICE_ROLE_KEY=<sr-key> SERVER_BASE_PATH=/tmp/mcontrol-empty uv run uvicorn mcontrol.main:app --port 8000`

(Substitute a real service-role key. Use `/tmp/mcontrol-empty` as a non-existent path so discovery is a no-op locally.)

Open `http://localhost:8000/` and verify:
- Empty state still renders cleanly when there are no rows in `app_mcontrol.servers`.
- The "Servers" eyebrow uses tokens.css typography (monospace, all-caps caption tone).

If you have rows in the deployed `app_mcontrol.servers` (e.g. you've manually inserted one for testing), pages render with the new card layout: name on the left, state on the right, the running/exited/etc. state coloured per the rule above.

Stop the server (Ctrl+C).

- [ ] **Step 4: Commit**

```bash
git add src/mcontrol/static/app.css
git commit -m "feat(design): server list + detail layouts (token-only)"
```

---

# Task 10: Mount `/var/run/docker.sock` into the app container

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Update the `app` service**

Edit `docker-compose.yml` — extend the `app` service with a `volumes` entry:

```yaml
services:
  app:
    build: .
    restart: unless-stopped
    env_file: .env
    expose:
      - "8000"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks:
      - internal
```

(Read-only is sufficient for `containers.list` + `container.show` — slice 4 will switch to `:rw` when adding lifecycle controls.)

- [ ] **Step 2: Confirm the file parses**

Run: `docker compose config | grep -A2 'volumes:' | head -10`
Expected: the output includes `/var/run/docker.sock:/var/run/docker.sock:ro`. (Skip on Windows dev where `docker compose` may not be available; verify on Linux dev or bserver.)

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "chore(deploy): mount docker socket read-only into app container"
```

---

# Task 11: End-to-end verification + PR

**Files:** none modified; verification only.

- [ ] **Step 1: Lint**

Run: `uv run ruff check .`
Expected: `All checks passed!` or equivalent. If anything trips, fix it inline and re-run.

- [ ] **Step 2: Run the full test suite**

Run: `uv run pytest -v`
Expected: every test passes. Approximate count: ~25 tests across settings, healthz, static, home (4), server_detail (4), db (7), docker_client (4), discovery (5), lifespan (2), no-hardcoded-styles (2). Whatever the total, all green.

- [ ] **Step 3: Live-DB smoke test against the deployed Supabase (Linux/macOS)**

Use a real `SERVICE_ROLE_KEY` from `bserver:~/repos/mcontrol/.env` and a temp directory containing no subdirs:

```bash
mkdir -p /tmp/mcontrol-smoke
export SUPABASE_URL=https://api.noelkleen.com
export SUPABASE_SERVICE_ROLE_KEY=<sr-key>
export SERVER_BASE_PATH=/tmp/mcontrol-smoke

uv run python -c "
import asyncio
from mcontrol import db, discovery
from pathlib import Path

async def main():
    n = await discovery.run_discovery(Path('/tmp/mcontrol-smoke'))
    print(f'discovered {n} dirs')
    print('rows in db:', db.list_servers())

asyncio.run(main())
"
```

Expected: `discovered 0 dirs` and `rows in db: []` (or whatever rows already exist on bserver — should be 0 if nothing else has populated the table). If the call raises `Schema 'app_mcontrol' does not exist or is not exposed`, slice 2 was incomplete.

Now create a temp dir and re-run:

```bash
mkdir /tmp/mcontrol-smoke/test-server-1
uv run python -c "
import asyncio
from mcontrol import db, discovery
from pathlib import Path

async def main():
    n = await discovery.run_discovery(Path('/tmp/mcontrol-smoke'))
    print(f'discovered {n} dirs')
    print('test-server-1 row:', db.get_server('test-server-1'))

asyncio.run(main())
"
```

Expected: `discovered 1 dirs` and `test-server-1 row: {...name: test-server-1, dir: /tmp/mcontrol-smoke/test-server-1, state: unknown, ...}`.

Clean up:

```bash
docker compose exec -T db psql -U postgres -d postgres -c "delete from app_mcontrol.servers where name = 'test-server-1'" 2>/dev/null || true
rm -rf /tmp/mcontrol-smoke
```

(The `psql` cleanup is bserver-only; skip on dev machines that aren't running the Supabase stack.)

- [ ] **Step 4: Push and open the PR**

```bash
git push -u origin slice3-server-discovery
gh pr create --title "Slice 3: server discovery + read-only server list" --body "$(cat <<'EOF'
## Summary
- New modules: `db.py` (supabase-py wrapper for `app_mcontrol.servers`), `docker_client.py` (aiodocker wrapper), `discovery.py` (walks `SERVER_BASE_PATH`, upserts rows).
- Discovery runs once at app startup via FastAPI lifespan; Docker socket mounted read-only into the `app` container.
- Home page now renders a real server list with state colour, falls back to the existing empty state when the table is empty.
- New `/servers/{name}` detail page (read-only — controls land in slice 4).
- All new CSS uses `tokens.css` variables only; the hardcoded-style guard remains green.

## Test plan
- [ ] `uv run pytest -v` is green (~25 tests).
- [ ] `uv run ruff check .` is green.
- [ ] Live-DB smoke test in Task 11 step 3 passes against the deployed Supabase.
- [ ] On bserver, `docker compose up -d --build` brings the app up and the home page lists the existing server directories.

Refs: docs/decisions.md (006, 007, 008, 011, 013, 016); docs/plans/2026-04-27-mcontrol-v1-slice3-server-discovery.md.
EOF
)"
```

---

## Self-review

**Spec coverage:** every component the user named is delivered — `db.py` (Task 3), `docker_client.py` (Task 4), discovery routine that walks `SERVER_BASE_PATH` (Task 5), `routes/server.py` for the per-server detail page (Task 8), home empty-state replaced with the real server list (Task 7). Decisions 006 (socket mount), 007 (`app_mcontrol`), 008 (path layout), 011 (service-role key), 013 (variables JSONB rendered) are all enacted. Decisions 010 (RCON column exists, generation deferred to slice 4 when the lifecycle code writes `.env`), 014 (image migration deferred to slice 8), and 018 (whitelist/ops UI deferred to slice 7) are explicitly deferred.

**Karpathy guidelines:**
- Discovery has one trigger: app startup. No timer, no button, no "if request count > N" — those are slice-4 decisions if we get there.
- `db.py` exposes only the three calls the slice actually uses (`list_servers`, `get_server`, `upsert_server`). No premature `delete_server` or `update_state`. When slice 4 needs them, they get added then.
- `docker_client.py` exposes only `container_states_by_name` — slice 4 will add `start`, `stop`, `restart`, `logs` as it needs them.
- The CSS additions are the minimum to render two specific surfaces (list, detail). No design system additions; everything chains off existing tokens.
- Docker socket mounted read-only because read-only is enough this slice; switching to read-write is a one-line slice-4 change.
- No retries, no exponential backoff, no circuit breaker on the supabase calls. If the DB is down, the request 500s; the operator restarts. v1 single-user posture.
- The supabase-py SDK is sync; no preemptive `asyncio.to_thread` wrapping. If the event loop ever measurably stalls, that's the fix; today it's noise.

**Verifiable success criteria:**
- Unit tests cover db wrapper chaining, docker wrapper happy/sad paths, discovery walk + upsert + sort + missing-base-path, home rendering (empty + populated + links), detail rendering (404 + happy + null image_base + back link), lifespan invocation + failure tolerance, settings docker_host default + override.
- Hardcoded-style guard stays green.
- Live smoke test against the deployed Supabase confirms slice 2 is correctly wired.

**Placeholder scan:** every code block is full and copy-pasteable; `<sr-key>` is the only stand-in and is explicitly defined as "the service-role key from `bserver:~/repos/mcontrol/.env`" each time it appears. No "TBD" / "implement later" / "similar to Task N".

**Type consistency:** `list_servers` returns `list[dict[str, Any]]` and the route consumes `servers` as a list of dicts in templates (`server.name`, `server.state`); `get_server` returns `dict | None` and the route 404s on `None`; `upsert_server` is keyword-only (`name=`, `dir=`, `state=`) and discovery + tests both call it that way. `container_states_by_name` returns `dict[str, str]` with stripped names; discovery uses `.get(name, "unknown")` consistently. The `_client_singleton` global is reset in `tests/test_db.py`'s `_reset_client_singleton` autouse fixture, so test ordering is stable.
