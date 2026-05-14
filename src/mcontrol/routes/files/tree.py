"""Tree-listing endpoint: full + dirs-only `?picker=1` variant."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from mcontrol import file_safety
from mcontrol.routes._dependencies import get_server_or_404
from mcontrol.routes.files._safety import _list_dir
from mcontrol.templates import templates

router = APIRouter()


@router.get("/servers/{name}/files/tree", response_class=HTMLResponse)
async def tree(
    request: Request,
    name: str,
    server: dict = Depends(get_server_or_404),
    path: str = Query(""),
    picker: bool = Query(False),
) -> HTMLResponse:
    """Render a directory listing.

    `picker=1` returns a dirs-only variant via `_file_dir_picker.html` for
    the move-destination modal (slice 5 PR 5). Lazy-load uses the same
    endpoint with the same flag so child fetches stay dirs-only.
    """
    target = file_safety.resolve_within(server["dir"], path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="path not found")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="not a directory")

    base = Path(server["dir"]).resolve()
    entries = _list_dir(target, base)
    if picker:
        entries = [e for e in entries if e["kind"] == "dir"]
        return templates.TemplateResponse(
            request=request,
            name="_file_dir_picker.html",
            context={"server_name": name, "entries": entries},
        )
    return templates.TemplateResponse(
        request=request,
        name="_file_tree.html",
        context={"server_name": name, "entries": entries},
    )
