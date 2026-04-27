from fastapi import FastAPI

from mcontrol.settings import Settings


def create_app() -> FastAPI:
    settings = Settings()
    app = FastAPI(title="mcontrol", version="0.1.0")
    app.state.settings = settings

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
