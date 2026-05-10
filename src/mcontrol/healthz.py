"""Deep readiness probe for /healthz (slice 11, decision 030).

Three subsystem probes — Supabase reachability, Docker socket
reachability, and the bind-mount base path being a writable directory
— run concurrently with a 250 ms per-probe budget. The endpoint
returns 200 when all three pass and 503 when any one fails so the
upstream nginx terminator (decision 019) can react.

Distinct from ``mcontrol.health`` (per-server scaffold-integrity for
the detail-page banner). Different question, different consumer,
different module.
"""

import asyncio
import os
import time
import uuid
from pathlib import Path
from typing import Any

import aiodocker

from mcontrol import db
from mcontrol.settings import Settings

_TIMEOUT_S = 0.25
_DETAIL_MAX = 200


def _sanitise(exc: BaseException) -> str:
    """One-line, length-capped exception summary suitable for the JSON
    body. ``repr(exc)`` could include attribute values inlined by
    third-party libraries (Settings holds the SUPABASE_SERVICE_ROLE_KEY,
    so an unlucky exception could leak it); ``f"{type(exc).__name__}: {exc}"``
    keeps the class name while giving the library only the message slot
    to render."""
    return f"{type(exc).__name__}: {exc}"[:_DETAIL_MAX]


async def _probe_db() -> dict[str, str]:
    try:
        await asyncio.wait_for(asyncio.to_thread(db.ping), _TIMEOUT_S)
    except TimeoutError:
        return {"status": "fail", "detail": "timeout after 250 ms"}
    except Exception as exc:
        return {"status": "fail", "detail": _sanitise(exc)}
    return {"status": "ok", "detail": "reachable"}


async def _probe_docker() -> dict[str, str]:
    settings = Settings()

    async def _ping() -> None:
        docker = aiodocker.Docker(url=settings.docker_host)
        try:
            # `docker.version()` is the lightest public round-trip in
            # aiodocker — `system.ping()` does not exist on this client
            # version (the `DockerSystem` class only exposes `info()`),
            # and `_query("_ping")` uses the underscore-prefixed private
            # API. `version()` hits `/version`, returns a small dict, and
            # confirms the daemon answers HTTP — exactly what we want.
            await docker.version()
        finally:
            try:
                await docker.close()
            except Exception:
                pass

    try:
        await asyncio.wait_for(_ping(), _TIMEOUT_S)
    except TimeoutError:
        return {"status": "fail", "detail": "timeout after 250 ms"}
    except Exception as exc:
        return {"status": "fail", "detail": _sanitise(exc)}
    return {"status": "ok", "detail": "reachable"}


def _write_probe_sync(base: Path) -> None:
    """is_dir + touch + unlink. Raises on any failure."""
    if not base.is_dir():
        raise FileNotFoundError(f"{base} is not a directory")
    probe = base / f".healthz-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    probe.touch()
    try:
        probe.unlink()
    except FileNotFoundError:
        pass


async def _probe_base_path() -> dict[str, str]:
    settings = Settings()
    base = Path(settings.server_base_path)
    try:
        await asyncio.wait_for(
            asyncio.to_thread(_write_probe_sync, base), _TIMEOUT_S
        )
    except TimeoutError:
        return {"status": "fail", "detail": "timeout after 250 ms"}
    except Exception as exc:
        return {"status": "fail", "detail": _sanitise(exc)}
    return {"status": "ok", "detail": str(base)}


async def build_report() -> tuple[int, dict[str, Any]]:
    """Run the three probes concurrently and assemble the JSON envelope.

    Returns ``(status_code, payload)``. Status code is 200 when every
    probe is ok, 503 otherwise. ``return_exceptions=True`` on the gather
    means a probe that raises past its own try/except still degrades
    its subsystem to "fail" rather than 500-ing the endpoint.
    """
    started = time.monotonic()
    probes = await asyncio.gather(
        _probe_db(),
        _probe_docker(),
        _probe_base_path(),
        return_exceptions=True,
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)

    keys = ("db", "docker", "base_path")
    checks: dict[str, dict[str, str]] = {}
    for key, result in zip(keys, probes, strict=True):
        if isinstance(result, BaseException):
            checks[key] = {"status": "fail", "detail": _sanitise(result)}
        else:
            checks[key] = result

    all_ok = all(c["status"] == "ok" for c in checks.values())
    payload: dict[str, Any] = {
        "status": "ok" if all_ok else "degraded",
        "checks": checks,
        "elapsed_ms": elapsed_ms,
    }
    return (200 if all_ok else 503, payload)
