_HTML = {"Accept": "text/html"}
_HTMX = {"Accept": "text/html", "HX-Request": "true"}


async def test_get_rescan_returns_html_405_for_browser(client):
    response = await client.get("/rescan", headers=_HTML)

    assert response.status_code == 405
    assert "text/html" in response.headers["content-type"]
    assert "error-page" in response.text
    assert "Method Not Allowed" in response.text
    assert '{"detail"' not in response.text


async def test_get_lifecycle_start_returns_html_405_for_browser(client):
    response = await client.get("/servers/atm10/lifecycle/start", headers=_HTML)

    assert response.status_code == 405
    assert "text/html" in response.headers["content-type"]
    assert "error-page" in response.text
    assert "Method Not Allowed" in response.text


async def test_get_rescan_returns_json_405_for_htmx(client):
    response = await client.get("/rescan", headers=_HTMX)

    assert response.status_code == 405
    assert response.json() == {"detail": "Method Not Allowed"}


async def test_get_rescan_returns_json_405_for_api_accept(client):
    response = await client.get("/rescan", headers={"Accept": "application/json"})

    assert response.status_code == 405
    assert response.json() == {"detail": "Method Not Allowed"}


async def test_static_missing_is_plain_text_404(client):
    response = await client.get("/static/nope.css", headers=_HTML)

    assert response.status_code == 404
    assert response.text == "not found"
    assert "text/plain" in response.headers["content-type"]
    assert "error-page" not in response.text
    assert "No servers yet" not in response.text


async def test_missing_page_still_renders_branded_404(client):
    response = await client.get("/does-not-exist", headers=_HTML)

    assert response.status_code == 404
    assert "text/html" in response.headers["content-type"]
    assert "error-page" in response.text
    assert "Not found" in response.text
    assert "/static/app.mcontrol.css" not in response.text
    assert "mcontrol-nav" not in response.text


async def test_missing_page_does_not_load_mcontrol_context(client, monkeypatch):
    from mcontrol.infra import db_async

    async def fail_servers():
        raise AssertionError("unrelated errors must not query MC servers")

    monkeypatch.setattr(db_async, "list_servers", fail_servers)

    response = await client.get("/does-not-exist", headers=_HTML)

    assert response.status_code == 404
    assert "mcontrol-nav" not in response.text


async def test_favicon_redirects_to_svg(client):
    response = await client.get("/favicon.ico", follow_redirects=False)

    assert response.status_code == 308
    assert response.headers["location"] == "/static/favicon.svg"


async def test_removed_trash_routes_return_404(client):
    for method, path in [
        ("GET", "/trash"),
        ("GET", "/trash/empty/confirm"),
        ("POST", "/trash/empty"),
        ("GET", "/trash/.deleted-example-1700000000/confirm"),
        ("POST", "/trash/.deleted-example-1700000000/delete"),
    ]:
        response = await client.request(method, path)
        assert response.status_code == 404
