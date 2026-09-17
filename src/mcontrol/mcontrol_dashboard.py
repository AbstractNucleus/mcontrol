import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

import aiodocker
import aiohttp
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from mcontrol.dashboards import Dashboard
from mcontrol.domain import discovery
from mcontrol.infra import db_async, docker_client, healthz
from mcontrol.infra import probe_host as probe_host_mod
from mcontrol.routes import (
    bindings,
    console,
    delete_server,
    files,
    home,
    lifecycle,
    logs,
    migrate,
    new_server,
    players,
    regenerate,
    server,
    server_players,
    server_resources,
    variables,
)
from mcontrol.settings import Settings

logger = logging.getLogger("mcontrol")

router = APIRouter()
router.include_router(home.router)
# /servers/new must stay ahead of /servers/{name}.
router.include_router(new_server.router)
router.include_router(server.router)
router.include_router(lifecycle.router)
router.include_router(logs.router)
router.include_router(console.router)
router.include_router(bindings.router)
router.include_router(variables.router)
router.include_router(regenerate.router)
router.include_router(migrate.router)
router.include_router(delete_server.router)
router.include_router(files.router)
router.include_router(server_players.router)
router.include_router(server_resources.router)
router.include_router(players.router)


@router.get("/healthz")
async def healthz_endpoint(request: Request) -> JSONResponse:
    status_code, payload = await healthz.build_report(request.app.state.docker)
    if status_code != 200:
        logger.warning("healthz degraded: %s", payload["checks"])
    return JSONResponse(status_code=status_code, content=payload)


async def page_context(request: Request) -> Mapping[str, Any]:
    path = request.url.path
    if (
        path.endswith("/logs")
        or path.endswith("/rcon")
        or path.endswith("/download")
    ):
        return {}

    try:
        servers = await db_async.list_servers()
    except Exception:
        servers = []

    return {"servers": servers}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    # One client serves all MC routes. The timeout bounds ordinary Docker API
    # calls; aiodocker removes total/sock_read for long-lived logs and stats.
    docker = aiodocker.Docker(
        url=settings.docker_host,
        timeout=aiohttp.ClientTimeout(total=60, connect=5, sock_read=30),
    )
    app.state.docker = docker

    try:
        await probe_host_mod.resolve(docker)
    except Exception:
        logger.warning("probe host resolve failed", exc_info=True)
    try:
        await docker_client.prune_stale_self_networks(docker)
    except Exception:
        logger.warning("stale network prune failed", exc_info=True)

    base_path = Path(settings.server_base_path)
    try:
        count = await discovery.run_discovery(docker, base_path)
        logger.info("discovery: %d server dir(s) seen under %s", count, base_path)
    except Exception:
        logger.exception("discovery failed; continuing without it")
    try:
        yield
    finally:
        with suppress(Exception):
            await docker_client.disconnect_refcount_networks(docker)
        with suppress(Exception):
            await docker.close()


dashboard = Dashboard(
    id="mcontrol",
    label="mcontrol",
    href="/",
    icon="server",
    router=router,
    page_context=page_context,
    lifespan=lifespan,
)
