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
