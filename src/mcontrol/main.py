import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import aiodocker
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from mcontrol import __version__, healthz
from mcontrol.domain import discovery, tombstones
from mcontrol.infra import db
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
    trash,
    variables,
)
from mcontrol.settings import Settings, get_settings
from mcontrol.templates import templates

STATIC_DIR = Path(__file__).parent / "static"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("mcontrol")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    # Single aiodocker client lives for the whole process lifetime
    # (decision #98). Routes inject it via Depends(get_docker); non-route
    # callers (discovery here, healthz, resources, server_rcon) get it
    # passed in explicitly.
    docker = aiodocker.Docker(url=settings.docker_host)
    app.state.docker = docker

    base_path = Path(settings.server_base_path)
    try:
        count = await discovery.run_discovery(docker, base_path)
        logger.info("discovery: %d server dir(s) seen under %s", count, base_path)
    except Exception:
        # Discovery must never block the app from coming up — the home page
        # surfaces an empty state and the operator can investigate from there.
        logger.exception("discovery failed; continuing without it")
    try:
        yield
    finally:
        with suppress(Exception):
            await docker.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="mcontrol", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings

    # Jinja global for the topnav badge (decision 035). Called from
    # _topnav.html on every page; uses tombstones.count() which is a
    # single scandir, so cheap to invoke per render.
    def _tombstone_count(request: Request) -> int:
        try:
            base = Path(request.app.state.settings.server_base_path)
            return tombstones.count(base)
        except Exception:
            return 0

    templates.env.globals["tombstone_count"] = _tombstone_count

    # Jinja global for the sidebar server list. Called from _sidebar.html on
    # every page — keeps the navigator in sync across detail pages without
    # threading `servers` through every route's context. Same defensive
    # try/except as tombstone_count so a DB blip can't take the chrome down.
    def _sidebar_servers(_request: Request) -> list[dict]:
        try:
            return db.list_servers()
        except Exception:
            return []

    templates.env.globals["sidebar_servers"] = _sidebar_servers

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(home.router)
    # new_server must register before server so /servers/new takes
    # precedence over /servers/{name}'s catch-all.
    app.include_router(new_server.router)
    app.include_router(server.router)
    app.include_router(lifecycle.router)
    app.include_router(logs.router)
    app.include_router(console.router)
    app.include_router(bindings.router)
    app.include_router(variables.router)
    app.include_router(regenerate.router)
    app.include_router(migrate.router)
    app.include_router(delete_server.router)
    app.include_router(files.router)
    app.include_router(server_players.router)
    app.include_router(server_resources.router)
    app.include_router(players.router)
    app.include_router(trash.router)

    @app.get("/healthz")
    async def healthz_endpoint(request: Request) -> JSONResponse:
        status_code, payload = await healthz.build_report(
            request.app.state.docker
        )
        return JSONResponse(status_code=status_code, content=payload)

    # Custom error pages (slice 12, decision 032). HTMX requests still
    # surface error JSON so swap targets behave; full-page navigations
    # render the chrome-shaped error template.
    def _wants_html(request: Request) -> bool:
        if request.headers.get("hx-request"):
            return False
        accept = request.headers.get("accept", "")
        return "text/html" in accept or accept == ""

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404 and _wants_html(request):
            return templates.TemplateResponse(
                request=request,
                name="404.html",
                context={"version": __version__, "detail": exc.detail},
                status_code=404,
            )
        # Default: forward to FastAPI's normal JSON shape so HTMX
        # consumers and 4xx/5xx forms keep working.
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=getattr(exc, "headers", None) or {},
        )

    @app.exception_handler(500)
    async def internal_error_handler(request: Request, exc: Exception):
        logger.exception("internal error: %s", exc)
        if _wants_html(request):
            return templates.TemplateResponse(
                request=request,
                name="500.html",
                context={"version": __version__},
                status_code=500,
            )
        return JSONResponse(
            status_code=500, content={"detail": "Internal server error"}
        )

    return app


app = create_app()
