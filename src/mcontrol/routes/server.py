from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from mcontrol import __version__, db
from mcontrol.templates import templates

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
