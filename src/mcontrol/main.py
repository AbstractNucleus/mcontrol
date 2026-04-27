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
