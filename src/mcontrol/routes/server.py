from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from mcontrol import __version__, db

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

router = APIRouter()


@router.get("/servers/{name}", response_class=HTMLResponse)
async def server_detail(request: Request, name: str) -> HTMLResponse:
    server = db.get_server(name)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")
    return templates.TemplateResponse(
        request=request,
        name="server_detail.html",
        context={"version": __version__, "server": server},
    )
