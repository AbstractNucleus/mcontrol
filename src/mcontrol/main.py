import logging
from collections.abc import Iterable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from mcontrol import __version__
from mcontrol.dashboards import Dashboard, DashboardRegistry
from mcontrol.mcontrol_dashboard import dashboard as mcontrol_dashboard
from mcontrol.routes._flash import COOKIE as FLASH_COOKIE
from mcontrol.routes._flash import read_flash
from mcontrol.settings import get_settings
from mcontrol.templates import templates

STATIC_DIR = Path(__file__).parent / "static"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("mcontrol")
logging.getLogger("httpx").setLevel(logging.WARNING)


class _HealthzAccessFilter(logging.Filter):
    """Drop uvicorn access lines for the liveness probe."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3:
            path = args[2]
            if isinstance(path, str) and path.split("?", 1)[0] == "/healthz":
                return False
        try:
            return "/healthz" not in record.getMessage()
        except Exception:
            return True


logging.getLogger("uvicorn.access").addFilter(_HealthzAccessFilter())


def _wants_html(request: Request) -> bool:
    if request.headers.get("hx-request"):
        return False
    accept = request.headers.get("accept", "")
    return "text/html" in accept or accept == ""


def create_app(dashboards: Iterable[Dashboard] | None = None) -> FastAPI:
    settings = get_settings()
    registered = tuple(dashboards) if dashboards is not None else (mcontrol_dashboard,)
    registry = DashboardRegistry(registered)

    @asynccontextmanager
    async def app_lifespan(app: FastAPI):
        async with registry.lifespan(app):
            yield

    app = FastAPI(title="mcontrol", version=__version__, lifespan=app_lifespan)
    app.state.settings = settings
    app.state.dashboard_registry = registry

    @app.middleware("http")
    async def _prepare_page(request: Request, call_next):
        dashboard = registry.match(request.scope)
        request.state.dashboard = dashboard
        request.state.dashboard_context = {}
        if request.url.path != "/healthz" and _wants_html(request):
            if dashboard is not None and dashboard.page_context is not None:
                request.state.dashboard_context = await dashboard.page_context(request)
            flash = read_flash(request)
            if flash:
                request.state.page_flash = flash
                request.state.clear_flash_cookie = True
        response = await call_next(request)
        if getattr(request.state, "clear_flash_cookie", False):
            response.delete_cookie(FLASH_COOKIE, path="/")
        return response

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    registry.install_routes(app)

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> RedirectResponse:
        return RedirectResponse(url="/static/favicon.svg", status_code=308)

    # Custom error pages. HTMX requests still
    # surface error JSON so swap targets behave; full-page navigations
    # render the chrome-shaped error template.
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        path = request.url.path
        if exc.status_code == 404 and (path == "/static" or path.startswith("/static/")):
            return PlainTextResponse("not found", status_code=404)
        if exc.status_code in (404, 405) and _wants_html(request):
            return templates.TemplateResponse(
                request=request,
                name="error.html",
                context={
                    "code": exc.status_code,
                    "title": "Not found" if exc.status_code == 404 else "Method not allowed",
                    "detail": exc.detail,
                    "icon_name": "search",
                },
                status_code=exc.status_code,
                headers=getattr(exc, "headers", None) or {},
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
                name="error.html",
                context={
                    "code": 500,
                    "title": "Something went wrong",
                    "detail": "The dashboard hit an internal error.",
                    "icon_name": "server",
                },
                status_code=500,
            )
        return JSONResponse(
            status_code=500, content={"detail": "Internal server error"}
        )

    return app


app = create_app()
