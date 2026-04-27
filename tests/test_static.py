async def test_tokens_css_is_served(client):
    response = await client.get("/static/tokens.css")

    assert response.status_code == 200
    assert "--main-color: #b5533a" in response.text
    assert response.headers["content-type"].startswith("text/css")
