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
