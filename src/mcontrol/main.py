import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from mcontrol import discovery
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

STATIC_DIR = Path(__file__).parent / "static"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
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

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
