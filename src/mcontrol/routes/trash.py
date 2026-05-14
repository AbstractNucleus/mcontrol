"""Trash listing + purge (slice 11, decision 031).

  GET  /trash                       → list every .deleted-<name>-<ts>/
                                       directory under <base> with parsed
                                       original-name, age, and bytes.
  POST /trash/empty                 → purge every tombstone older than
                                       DEFAULT_PURGE_AGE_DAYS (7); type
                                       'EMPTY' to confirm.
  POST /trash/{dir_name}/delete     → purge that single tombstone; type
                                       the parsed original server name to
                                       confirm.

Path-safety lives in tombstones.purge_one; routes only validate the
type-name confirm string before delegating.
"""

import asyncio
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from mcontrol import __version__
from mcontrol.domain import tombstones
from mcontrol.resources import format_bytes
from mcontrol.settings import Settings
from mcontrol.templates import templates

router = APIRouter()


def _humanize_age(seconds: int) -> str:
    """Render an age in seconds as a short human string: '5d 3h',
    '2h 14m', '47s'. Two granularities maximum, smallest unit first
    becomes lossy fast — we render largest unit + the next one."""
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        m, s = divmod(seconds, 60)
        return f"{m}m {s}s"
    if seconds < 86400:
        h, rem = divmod(seconds, 3600)
        m = rem // 60
        return f"{h}h {m}m"
    d, rem = divmod(seconds, 86400)
    h = rem // 3600
    return f"{d}d {h}h"


def _base(request: Request) -> Path:
    settings: Settings = request.app.state.settings
    return Path(settings.server_base_path)


def _list_view(base: Path) -> dict:
    rows = tombstones.list_tombstones(base)
    cutoff = tombstones.DEFAULT_PURGE_AGE_DAYS * 86400
    sweepable = [t for t in rows if t.age_seconds >= cutoff]
    sweep_bytes = sum(t.bytes for t in sweepable)
    return {
        "version": __version__,
        "tombstones": [
            {
                "dir_name": t.dir_name,
                "original_name": t.original_name,
                "age_human": _humanize_age(t.age_seconds),
                "bytes_human": format_bytes(t.bytes),
            }
            for t in rows
        ],
        "sweep_count": len(sweepable),
        "sweep_bytes_human": format_bytes(sweep_bytes),
        "purge_age_days": tombstones.DEFAULT_PURGE_AGE_DAYS,
    }


@router.get("/trash", response_class=HTMLResponse)
async def get_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request, name="trash.html", context=_list_view(_base(request))
    )


@router.get("/trash/empty/confirm", response_class=HTMLResponse)
async def empty_confirm(request: Request) -> HTMLResponse:
    """Modal partial — the count + bytes preview before the operator
    types 'EMPTY' to confirm."""
    base = _base(request)
    cutoff = tombstones.DEFAULT_PURGE_AGE_DAYS * 86400
    sweepable = [
        t for t in tombstones.list_tombstones(base) if t.age_seconds >= cutoff
    ]
    return templates.TemplateResponse(
        request=request,
        name="_trash_empty_confirm.html",
        context={
            "sweepable": [
                {
                    "dir_name": t.dir_name,
                    "original_name": t.original_name,
                    "age_human": _humanize_age(t.age_seconds),
                    "bytes_human": format_bytes(t.bytes),
                }
                for t in sweepable
            ],
            "purge_age_days": tombstones.DEFAULT_PURGE_AGE_DAYS,
        },
    )


@router.post("/trash/empty", response_class=HTMLResponse)
async def empty(request: Request, confirm: str = Form("")) -> HTMLResponse:
    if confirm.strip() != "EMPTY":
        raise HTTPException(
            status_code=422,
            detail="Type EMPTY (uppercase) to confirm.",
        )
    await asyncio.to_thread(tombstones.purge_older_than, _base(request))
    response = HTMLResponse("", status_code=200)
    response.headers["HX-Redirect"] = "/trash"
    return response


@router.get("/trash/{dir_name}/confirm", response_class=HTMLResponse)
async def delete_confirm(request: Request, dir_name: str) -> HTMLResponse:
    """Modal partial — type-name confirm for a single tombstone delete."""
    parsed = tombstones.parse(dir_name)
    if parsed is None:
        raise HTTPException(status_code=404, detail="Not a tombstone")
    original_name, _ts = parsed
    return templates.TemplateResponse(
        request=request,
        name="_trash_delete_confirm.html",
        context={"dir_name": dir_name, "original_name": original_name},
    )


@router.post("/trash/{dir_name}/delete", response_class=HTMLResponse)
async def delete(
    request: Request, dir_name: str, confirm_name: str = Form("")
) -> HTMLResponse:
    parsed = tombstones.parse(dir_name)
    if parsed is None:
        raise HTTPException(status_code=404, detail="Not a tombstone")
    original_name, _ts = parsed
    if confirm_name.strip() != original_name:
        raise HTTPException(
            status_code=422,
            detail=f"Type the server name ({original_name!r}) to confirm.",
        )
    try:
        await asyncio.to_thread(tombstones.purge_one, _base(request), dir_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    response = HTMLResponse("", status_code=200)
    response.headers["HX-Redirect"] = "/trash"
    return response
