"""Shared Jinja2Templates instance for all mcontrol routes.

Slice 3 inlined `Jinja2Templates(directory=TEMPLATES_DIR)` in both
routes/home.py and routes/server.py. Slice 4 adds four more route
modules; sharing a single instance keeps configuration in one place.
"""

from datetime import datetime
from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from mcontrol import health

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def humansize(size: int) -> str:
    """Format a byte count for the file-view metadata caption (issue #60).

    Bytes for <1 KB, KB with one decimal for <1 MB, MB with one decimal
    otherwise. 1 KB = 1024 B. Negative inputs aren't expected from stat()
    and fall through as bytes.
    """
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def humantime(mtime_ns: int) -> str:
    """Format a stat-mtime nanosecond count as a local-zone caption.

    Used by the file-view metadata header (issue #60). The output is
    unambiguous date + time in local zone; seconds precision is enough
    for "when did this change" UX without leaking the noisy nanos.
    """
    return datetime.fromtimestamp(mtime_ns / 1e9).strftime("%Y-%m-%d %H:%M:%S")


templates.env.filters["humansize"] = humansize
templates.env.filters["humantime"] = humantime


def render_variables_card(request: Request, server: dict) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="_variables_card.html",
        context={
            "server": server,
            "variables_error": health.variables_render_error(server),
            "scripts_stale": health.compute_scripts_stale(server),
        },
    )
