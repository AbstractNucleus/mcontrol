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

from mcontrol.domain import health
from mcontrol.infra.resources import format_bytes

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def humantime(mtime_ns: int) -> str:
    """Format a stat-mtime nanosecond count as a local-zone caption.

    Used by the file-view metadata header (issue #60). The output is
    unambiguous date + time in local zone; seconds precision is enough
    for "when did this change" UX without leaking the noisy nanos.
    """
    return datetime.fromtimestamp(mtime_ns / 1e9).strftime("%Y-%m-%d %H:%M:%S")


templates.env.filters["humansize"] = format_bytes
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
