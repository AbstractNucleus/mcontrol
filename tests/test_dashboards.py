from contextlib import asynccontextmanager

import pytest
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from httpx import ASGITransport, AsyncClient

from mcontrol.dashboards import Dashboard
from mcontrol.mcontrol_dashboard import dashboard as mcontrol_dashboard
from mcontrol.templates import templates


def _tiny_dashboard() -> Dashboard:
    router = APIRouter()

    @router.get("/tiny", response_class=HTMLResponse)
    async def tiny(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request=request, name="base.html", context={})

    return Dashboard(
        id="tiny",
        label="Tiny",
        href="/tiny",
        icon="grid",
        router=router,
    )


async def test_registered_dashboard_owns_route_sidebar_and_generic_assets(
    env, monkeypatch
):
    from mcontrol.infra import db_async
    from mcontrol.main import create_app

    calls = {"servers": 0}

    async def fail_servers():
        calls["servers"] += 1
        raise AssertionError("MC context must not load for another dashboard")

    monkeypatch.setattr(db_async, "list_servers", fail_servers)

    app = create_app((mcontrol_dashboard, _tiny_dashboard()))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/tiny", headers={"Accept": "text/html"})

    assert response.status_code == 200
    body = response.text
    tiny_start = body.index('href="/tiny"')
    tiny_link = body[tiny_start : body.index("</a>", tiny_start)]
    mcontrol_start = body.index('title="mcontrol dashboard"')
    mcontrol_link = body[mcontrol_start : body.index("</a>", mcontrol_start)]
    assert 'aria-current="page"' in tiny_link
    assert 'aria-current="page"' not in mcontrol_link
    assert "/static/sidebar.js" in body
    assert "/static/app.mcontrol.css" not in body
    assert "/static/app.server.css" not in body
    assert "/static/app.workspace.css" not in body
    assert "/static/workspace.js" not in body
    assert "mcontrol-nav" not in body
    assert calls == {"servers": 0}


async def test_dashboard_registries_are_isolated_per_app(env):
    from mcontrol.main import create_app

    app_with_tiny = create_app((mcontrol_dashboard, _tiny_dashboard()))
    default_app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app_with_tiny), base_url="http://test"
    ) as client:
        assert (await client.get("/tiny")).status_code == 200

    async with AsyncClient(
        transport=ASGITransport(app=default_app), base_url="http://test"
    ) as client:
        response = await client.get("/missing", headers={"Accept": "text/html"})

    assert response.status_code == 404
    assert "Tiny" not in response.text


def test_mcontrol_route_order_keeps_new_server_before_name_route():
    paths = [route.path for route in mcontrol_dashboard.router.routes]
    assert paths.index("/servers/new") < paths.index("/servers/{name}")


async def test_dashboard_page_context_reaches_templates_and_skips_htmx(env):
    from mcontrol.main import create_app

    router = APIRouter()
    page = templates.env.from_string(
        "{{ dashboard_context(request).get('message', 'missing') }}"
    )
    calls = 0

    async def page_context(_request: Request):
        nonlocal calls
        calls += 1
        return {"message": "ready"}

    @router.get("/context", response_class=HTMLResponse)
    async def context_page(request: Request) -> HTMLResponse:
        return HTMLResponse(page.render(request=request))

    dashboard = Dashboard(
        id="context",
        label="Context",
        href="/context",
        icon="grid",
        router=router,
        page_context=page_context,
    )
    app = create_app((dashboard,))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        full_page = await client.get("/context", headers={"Accept": "text/html"})
        partial = await client.get(
            "/context",
            headers={"Accept": "text/html", "HX-Request": "true"},
        )

    assert full_page.text == "ready"
    assert partial.text == "missing"
    assert calls == 1


async def test_dashboard_lifespan_cleans_up_when_later_startup_fails(env):
    from mcontrol.main import create_app

    events = []

    @asynccontextmanager
    async def first_lifespan(_app):
        events.append("first started")
        try:
            yield
        finally:
            events.append("first stopped")

    @asynccontextmanager
    async def failing_lifespan(_app):
        events.append("second started")
        raise RuntimeError("startup failed")
        yield

    first = Dashboard(
        id="first",
        label="First",
        href="/first",
        icon="grid",
        router=APIRouter(),
        lifespan=first_lifespan,
    )
    second = Dashboard(
        id="second",
        label="Second",
        href="/second",
        icon="grid",
        router=APIRouter(),
        lifespan=failing_lifespan,
    )
    app = create_app((first, second))

    with pytest.raises(RuntimeError, match="startup failed"):
        async with app.router.lifespan_context(app):
            pass

    assert events == ["first started", "second started", "first stopped"]
