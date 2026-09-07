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


async def test_missing_page_sidebar_lists_servers(client, monkeypatch):
    from mcontrol.infra import db

    monkeypatch.setattr(
        db, "list_servers", lambda: [{"name": "atm10", "state": "exited"}]
    )

    response = await client.get("/does-not-exist", headers=_HTML)

    assert response.status_code == 404
    assert "atm10" in response.text
    assert "No servers yet." not in response.text


async def test_missing_page_empty_accept_still_primes_sidebar(client, monkeypatch):
    from mcontrol.infra import db

    monkeypatch.setattr(
        db, "list_servers", lambda: [{"name": "atm10", "state": "exited"}]
    )

    response = await client.get("/does-not-exist", headers={"Accept": ""})

    assert response.status_code == 404
    assert "text/html" in response.headers["content-type"]
    assert "atm10" in response.text
    assert "No servers yet." not in response.text


async def test_favicon_redirects_to_svg(client):
    response = await client.get("/favicon.ico", follow_redirects=False)

    assert response.status_code == 308
    assert response.headers["location"] == "/static/favicon.svg"
