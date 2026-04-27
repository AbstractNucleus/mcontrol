async def test_tokens_css_is_served(client):
    response = await client.get("/static/tokens.css")

    assert response.status_code == 200
    assert "--main-color: #b5533a" in response.text
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
