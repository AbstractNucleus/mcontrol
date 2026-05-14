async def test_tokens_css_is_served(client):
    response = await client.get("/static/tokens.css")

    assert response.status_code == 200
    # Slice 12 / decision 032: Claude-flavoured tokens. The accent
    # `#D97757` is the brand-orange anchor and gates the file having
    # gone through the slice-12 swap.
    assert "--accent:" in response.text
    assert "#D97757" in response.text
    assert response.headers["content-type"].startswith("text/css")


async def test_htmx_is_served(client):
    response = await client.get("/static/htmx.min.js")
    assert response.status_code == 200
    content_type = response.headers["content-type"]
    assert content_type.startswith(("application/javascript", "text/javascript"))
    assert len(response.content) > 30_000


async def test_htmx_sse_extension_is_served(client):
    response = await client.get("/static/htmx-ext-sse.js")
    assert response.status_code == 200
    content_type = response.headers["content-type"]
    assert content_type.startswith(("application/javascript", "text/javascript"))


async def test_flash_js_is_served(client):
    response = await client.get("/static/flash.js")
    assert response.status_code == 200
    content_type = response.headers["content-type"]
    assert content_type.startswith(("application/javascript", "text/javascript"))


async def test_modals_js_is_served(client):
    # Decision 037: shared focus-trap / return-focus helper for the three
    # overlay modals (player-remove, trash-empty, trash-delete).
    response = await client.get("/static/modals.js")
    assert response.status_code == 200
    content_type = response.headers["content-type"]
    assert content_type.startswith(("application/javascript", "text/javascript"))
    # Gate on the two opt-in attributes and the two slot ids the helper
    # wires, so the contract between the module and the templates stays
    # checked in one place.
    body = response.text
    assert "data-modal-root" in body
    assert "data-modal-close" in body
    assert "player-modal" in body
    assert "trash-modal" in body
