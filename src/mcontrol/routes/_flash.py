"""Persist a toast across HX-Redirect via the existing #flash-stack cookie.

Delete / trash purge return an empty body plus HX-Redirect, so an OOB
swap never lands. The next full page reads this cookie and renders
``_flash.html`` into ``#flash-stack``.
"""

from urllib.parse import quote, unquote

from fastapi import Request
from fastapi.responses import HTMLResponse, Response

COOKIE = "mcontrol-flash"
_KINDS = frozenset({"ok", "info", "error"})


def set_flash(response: Response, kind: str, message: str) -> None:
    if kind not in _KINDS:
        raise ValueError(f"unknown flash kind: {kind!r}")
    response.set_cookie(
        COOKIE,
        quote(f"{kind}|{message}", safe=""),
        max_age=60,
        httponly=True,
        samesite="lax",
        path="/",
    )


def read_flash(request: Request) -> dict[str, str] | None:
    raw = request.cookies.get(COOKIE)
    if not raw:
        return None
    decoded = unquote(raw)
    kind, sep, message = decoded.partition("|")
    if not sep or kind not in _KINDS or not message:
        return None
    return {"kind": kind, "message": message}


def hx_redirect(url: str, *, kind: str, message: str) -> HTMLResponse:
    response = HTMLResponse("", status_code=200)
    set_flash(response, kind, message)
    response.headers["HX-Redirect"] = url
    return response
