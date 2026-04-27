async def test_home_renders_wordmark(client):
    response = await client.get("/")

    assert response.status_code == 200
    body = response.text
    assert "mcontrol" in body
    # tokens.css is the only color/type/spacing source — verify it's linked
    assert '/static/tokens.css' in body
    # app.css applies layout — verify it's linked
    assert '/static/app.css' in body


async def test_home_shows_empty_state(client):
    response = await client.get("/")

    # Slice 1 has no real server data; an empty-state message is expected.
    assert response.status_code == 200
    assert "No servers yet" in response.text
