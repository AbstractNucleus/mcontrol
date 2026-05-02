from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from mcontrol import __version__, db
from mcontrol.templates import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    servers = db.list_servers()
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"version": __version__, "servers": servers},
    )
