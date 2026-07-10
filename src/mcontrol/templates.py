"""Shared Jinja2Templates instance for all mcontrol routes.

Slice 3 inlined `Jinja2Templates(directory=TEMPLATES_DIR)` in both
routes/home.py and routes/server.py. Slice 4 adds four more route
modules; sharing a single instance keeps configuration in one place.
"""

import re
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from mcontrol import __version__
from mcontrol.domain import health, lifecycle_state
from mcontrol.infra.resources import format_bytes

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Every page's base.html needs `version` for asset cache-busting and the
# sidebar brand; a global means no route can forget to pass it.
templates.env.globals["version"] = __version__


def humantime(mtime_ns: int) -> str:
    """Format a stat-mtime nanosecond count as a local-zone caption.

    Used by the file-view metadata header (issue #60). The output is
    unambiguous date + time in local zone; seconds precision is enough
    for "when did this change" UX without leaking the noisy nanos.
    """
    return datetime.fromtimestamp(mtime_ns / 1e9).strftime("%Y-%m-%d %H:%M:%S")


def _parse_iso(value: str) -> datetime | None:
    """Parse an ISO-8601 timestamp defensively.

    Docker's StartedAt carries 9-digit fractional seconds and a Z suffix,
    both beyond fromisoformat's tolerance on some inputs; trim to
    microseconds and normalise the offset. Returns None on anything
    unparseable and for Docker's zero-value sentinel (year 1)."""
    trimmed = re.sub(r"\.(\d{1,6})\d*", r".\1", value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(trimmed)
    except ValueError:
        return None
    if parsed.year < 2000:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _split_units(seconds: int) -> str:
    """'47s', '14m', '3h 12m', '5d 3h': largest unit plus one refinement."""
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        h, rem = divmod(seconds, 3600)
        return f"{h}h {rem // 60}m"
    d, rem = divmod(seconds, 86400)
    return f"{d}d {rem // 3600}h"


def uptime(started_at: str | None) -> str:
    """Docker State.StartedAt → 'up 3h 12m', or '' when unknown."""
    if not started_at:
        return ""
    parsed = _parse_iso(started_at)
    if parsed is None:
        return ""
    seconds = int((datetime.now(UTC) - parsed).total_seconds())
    if seconds < 0:
        return ""
    return f"up {_split_units(seconds)}"


def reltime(value: str | None) -> str:
    """ISO timestamp → '3m ago' / '5d 2h ago', or '' when unparseable."""
    if not value:
        return ""
    parsed = _parse_iso(str(value))
    if parsed is None:
        return ""
    seconds = int((datetime.now(UTC) - parsed).total_seconds())
    # Negative = clock skew; treat as "just now" rather than lying harder.
    if seconds < 5:
        return "just now"
    return f"{_split_units(seconds)} ago"


templates.env.filters["humansize"] = format_bytes
templates.env.filters["humantime"] = humantime
templates.env.filters["uptime"] = uptime
templates.env.filters["reltime"] = reltime

# Used by _fleet_row.html to derive per-row quick-action button state.
templates.env.globals["lifecycle_view"] = lifecycle_state.view


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
