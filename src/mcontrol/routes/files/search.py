"""Basename search endpoint.

The index itself lives in `mcontrol.services.file_search`. This
module owns the request shape (`q`, `include_chunks`), the result cap,
and the htmx template choice. The skip-set rules apply at index-build
time inside `file_search`, not here.
"""

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse

from mcontrol.routes._dependencies import get_server_or_404
from mcontrol.services import file_search
from mcontrol.templates import templates

router = APIRouter()

_SEARCH_LIMIT = 200
_SEARCH_MIN_LEN = 2


@router.get("/servers/{name}/files/search", response_class=HTMLResponse)
async def search(
    request: Request,
    name: str,
    server: dict = Depends(get_server_or_404),
    q: str = Query(""),
    include_chunks: bool = Query(False),
) -> HTMLResponse:
    """Recursive case-insensitive basename search (slice 5 PR 7).

    Consults a per-server in-memory index (built lazily, invalidated on
    mutation, TTL-refreshed) rather than re-walking on every keystroke
   . see issue #49. Symlinked directories are not descended at index
    build time; their link entries can still match by name. Special
    files are filtered at build time too. Capped at `_SEARCH_LIMIT` hits
    to keep render bounded on large trees.

    By default the index excludes well-known high-cardinality Minecraft
    world subdirs (chunk regions, per-player data, etc.) when they sit
    under a `world` or `DIM*` parent. Pass `include_chunks=1` to query an
    alternate index that includes them.
    """
    needle = q.strip().lower()
    if len(needle) < _SEARCH_MIN_LEN:
        return templates.TemplateResponse(
            request=request,
            name="_file_search_results.html",
            context={
                "server_name": name,
                "q": q,
                "results": [],
                "truncated": False,
                "too_short": bool(needle),
                "skipped": False,
            },
        )

    base = Path(server["dir"]).resolve()
    entries, skipped = await asyncio.to_thread(
        file_search.get_search_index, name, base, include_chunks
    )

    results: list[dict] = []
    truncated = False
    for name_lower, rel, kind in entries:
        if needle not in name_lower:
            continue
        results.append({"name": Path(rel).name, "path": rel, "kind": kind})
        if len(results) >= _SEARCH_LIMIT:
            truncated = True
            break

    return templates.TemplateResponse(
        request=request,
        name="_file_search_results.html",
        context={
            "server_name": name,
            "q": q,
            "results": results,
            "truncated": truncated,
            "too_short": False,
            "skipped": skipped,
        },
    )
