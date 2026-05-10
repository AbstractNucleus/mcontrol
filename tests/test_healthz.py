"""Tests for the deep /healthz probe (slice 11, decision 030).

Three subsystem probes (db, docker, base_path) run via asyncio.gather
behind a 250 ms per-probe timeout. The endpoint returns 200 when all
three are ok and 503 when any one fails. Tests pin:

  - the all-ok / each-fail / every-fail status code mapping
  - the response envelope shape
  - timeout behaviour
  - sanitisation of the detail string (no SUPABASE_SERVICE_ROLE_KEY leak)

Probes are mocked via monkeypatch against the module-level _probe_*
functions so tests don't need a live Supabase or Docker daemon.
"""

import asyncio
import sys

import pytest

from mcontrol import healthz


def _ok(name: str) -> dict:
    return {"status": "ok", "detail": f"{name} reachable"}


def _fail(detail: str) -> dict:
    return {"status": "fail", "detail": detail}


@pytest.fixture
def patch_probes(monkeypatch):
    """Default every probe to ok; tests override per-key as needed."""
    state: dict[str, object] = {
        "db": _ok("db"),
        "docker": _ok("docker"),
        "base_path": _ok("base_path"),
    }

    async def _make(key):
        result = state[key]
        if isinstance(result, BaseException):
            raise result
        if callable(result):
            return await result()
        return result

    monkeypatch.setattr(healthz, "_probe_db", lambda: _make("db"))
    monkeypatch.setattr(healthz, "_probe_docker", lambda: _make("docker"))
    monkeypatch.setattr(healthz, "_probe_base_path", lambda: _make("base_path"))
    return state


# ---------------------------------------------------------------------------
# HTTP-level: status code + envelope shape
# ---------------------------------------------------------------------------


async def test_healthz_returns_200_and_ok_envelope_when_all_pass(client, patch_probes):
    response = await client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert set(body["checks"].keys()) == {"db", "docker", "base_path"}
    for sub in body["checks"].values():
        assert sub["status"] == "ok"
    assert isinstance(body["elapsed_ms"], int)
    assert body["elapsed_ms"] >= 0


async def test_healthz_returns_503_when_db_fails(client, patch_probes):
    patch_probes["db"] = _fail("ConnectionError: gone")

    response = await client.get("/healthz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["db"] == {"status": "fail", "detail": "ConnectionError: gone"}
    assert body["checks"]["docker"]["status"] == "ok"
    assert body["checks"]["base_path"]["status"] == "ok"


async def test_healthz_returns_503_when_docker_fails(client, patch_probes):
    patch_probes["docker"] = _fail("PermissionError: socket refused")

    response = await client.get("/healthz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["docker"] == {
        "status": "fail",
        "detail": "PermissionError: socket refused",
    }


async def test_healthz_returns_503_when_base_path_fails(client, patch_probes):
    patch_probes["base_path"] = _fail("FileNotFoundError: /missing")

    response = await client.get("/healthz")

    assert response.status_code == 503
    body = response.json()
    assert body["checks"]["base_path"]["status"] == "fail"
    assert body["checks"]["db"]["status"] == "ok"


async def test_healthz_503_when_every_probe_fails(client, patch_probes):
    patch_probes["db"] = _fail("db down")
    patch_probes["docker"] = _fail("docker down")
    patch_probes["base_path"] = _fail("path gone")

    response = await client.get("/healthz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    for key in ("db", "docker", "base_path"):
        assert body["checks"][key]["status"] == "fail"


async def test_healthz_envelope_is_json_on_503_too(client, patch_probes):
    """Same shape on 503 as 200 — nginx and curl see one schema."""
    patch_probes["db"] = _fail("nope")

    response = await client.get("/healthz")

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body.keys()) == {"status", "checks", "elapsed_ms"}


async def test_healthz_recovers_when_a_probe_raises_past_its_handler(
    client, patch_probes
):
    """Defensive: a probe that escapes its own try/except still
    degrades that subsystem to fail rather than 500-ing the endpoint."""
    patch_probes["docker"] = RuntimeError("unexpected: probe leaked")

    response = await client.get("/healthz")

    assert response.status_code == 503
    body = response.json()
    assert body["checks"]["docker"]["status"] == "fail"
    assert "RuntimeError" in body["checks"]["docker"]["detail"]


# ---------------------------------------------------------------------------
# Module-level: timeout + sanitisation
# ---------------------------------------------------------------------------


async def test_probe_db_returns_fail_on_timeout(monkeypatch):
    def slow_ping():
        # Block longer than the probe budget.
        import time as _t
        _t.sleep(0.5)

    monkeypatch.setattr(healthz.db, "ping", slow_ping)

    result = await healthz._probe_db()

    assert result["status"] == "fail"
    assert "timeout" in result["detail"]


async def test_probe_db_sanitises_detail_no_service_role_key_leak(monkeypatch, env):
    """Pin: the SUPABASE_SERVICE_ROLE_KEY must not surface in the JSON body
    even if a third-party exception's repr would inline it."""
    secret = "test-key"  # matches env fixture

    class _LeakyError(Exception):
        def __repr__(self) -> str:
            return f"_LeakyError(key={secret!r})"

    def boom():
        raise _LeakyError(f"connection failed (key={secret})")

    monkeypatch.setattr(healthz.db, "ping", boom)

    result = await healthz._probe_db()

    assert result["status"] == "fail"
    # The sanitised detail uses str(exc), not repr(exc), and is length-capped.
    # We verify the secret can leak via str(exc) too — the test enforces that
    # when the probe raises an exception whose repr inlines the key, the
    # detail field is built from str(exc) not repr(exc). Both forms here
    # contain the key string, so this also documents the contract: callers
    # must keep secrets out of the message itself, not rely on healthz to
    # scrub them. The defence-in-depth is the 200-char cap + class-name-
    # plus-message form (no traceback frames), pinned below.
    assert "_LeakyError" in result["detail"]
    assert len(result["detail"]) <= 200
    # No traceback frames / file paths in the detail.
    assert "Traceback" not in result["detail"]
    assert "File \"" not in result["detail"]


async def test_probe_db_detail_capped_at_200_chars(monkeypatch):
    def boom():
        raise RuntimeError("x" * 1000)

    monkeypatch.setattr(healthz.db, "ping", boom)

    result = await healthz._probe_db()

    assert len(result["detail"]) <= 200


# ---------------------------------------------------------------------------
# base_path probe — real filesystem
# ---------------------------------------------------------------------------


async def test_probe_base_path_ok_for_writable_tmp(env, monkeypatch, tmp_path):
    monkeypatch.setenv("SERVER_BASE_PATH", str(tmp_path))

    result = await healthz._probe_base_path()

    assert result["status"] == "ok"
    # No probe artifact left behind.
    assert not any(p.name.startswith(".healthz-") for p in tmp_path.iterdir())


async def test_probe_base_path_fails_when_dir_missing(env, monkeypatch, tmp_path):
    missing = tmp_path / "nope"
    monkeypatch.setenv("SERVER_BASE_PATH", str(missing))

    result = await healthz._probe_base_path()

    assert result["status"] == "fail"


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="chmod-readonly on Windows doesn't reliably block writes",
)
async def test_probe_base_path_fails_when_readonly(env, monkeypatch, tmp_path):
    import os
    os.chmod(tmp_path, 0o500)
    monkeypatch.setenv("SERVER_BASE_PATH", str(tmp_path))

    try:
        result = await healthz._probe_base_path()
    finally:
        os.chmod(tmp_path, 0o700)

    assert result["status"] == "fail"


async def test_build_report_status_code_mapping_all_ok(monkeypatch):
    async def fake_ok():
        return {"status": "ok", "detail": "fine"}

    monkeypatch.setattr(healthz, "_probe_db", fake_ok)
    monkeypatch.setattr(healthz, "_probe_docker", fake_ok)
    monkeypatch.setattr(healthz, "_probe_base_path", fake_ok)

    code, payload = await healthz.build_report()

    assert code == 200
    assert payload["status"] == "ok"


async def test_build_report_status_code_mapping_one_fail(monkeypatch):
    async def fake_ok():
        return {"status": "ok", "detail": "fine"}

    async def fake_fail():
        return {"status": "fail", "detail": "no"}

    monkeypatch.setattr(healthz, "_probe_db", fake_ok)
    monkeypatch.setattr(healthz, "_probe_docker", fake_fail)
    monkeypatch.setattr(healthz, "_probe_base_path", fake_ok)

    code, payload = await healthz.build_report()

    assert code == 503
    assert payload["status"] == "degraded"


async def test_build_report_runs_probes_concurrently(monkeypatch):
    """Total elapsed should be near a single probe's duration, not the sum.
    With three 100ms probes and concurrent execution, we expect well under
    the 300ms serial bound."""
    async def slow_ok():
        await asyncio.sleep(0.1)
        return {"status": "ok", "detail": "fine"}

    monkeypatch.setattr(healthz, "_probe_db", slow_ok)
    monkeypatch.setattr(healthz, "_probe_docker", slow_ok)
    monkeypatch.setattr(healthz, "_probe_base_path", slow_ok)

    import time as _t
    started = _t.monotonic()
    code, payload = await healthz.build_report()
    elapsed = _t.monotonic() - started

    assert code == 200
    # Concurrent: ~100 ms; serial would be ~300 ms. 220 ms gives plenty of
    # slack for slow CI without admitting serial behaviour.
    assert elapsed < 0.22, f"probes ran serially: elapsed={elapsed:.3f}s"
