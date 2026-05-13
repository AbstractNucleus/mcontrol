import httpx
import pytest

from mcontrol import mojang


def _patch_async_client(monkeypatch, handler):
    """Replace ``mcontrol.mojang.httpx.AsyncClient`` with a factory that
    builds a real AsyncClient backed by an httpx.MockTransport using
    ``handler``. Lets the test assert the URL and stub the response
    without touching the network."""
    real_async_client = httpx.AsyncClient

    def factory(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(**kwargs)

    monkeypatch.setattr(mojang.httpx, "AsyncClient", factory)


async def test_lookup_returns_canonical_uuid_on_200(monkeypatch):
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={"id": "069a79f444e94726a5befca90e38aaf5", "name": "Notch"},
        )

    _patch_async_client(monkeypatch, handler)

    result = await mojang.lookup_by_name("Notch")

    assert captured["url"] == (
        "https://api.minecraftservices.com/minecraft/profile/lookup/name/Notch"
    )
    assert result == {
        "uuid": "069a79f4-44e9-4726-a5be-fca90e38aaf5",
        "name": "Notch",
    }


async def test_lookup_returns_none_on_204(monkeypatch):
    def handler(request):
        return httpx.Response(204)

    _patch_async_client(monkeypatch, handler)

    assert await mojang.lookup_by_name("nope") is None


async def test_lookup_raises_on_5xx(monkeypatch):
    # Both endpoints return 5xx → MojangError after both are tried.
    def handler(request):
        return httpx.Response(503, text="upstream gone")

    _patch_async_client(monkeypatch, handler)

    with pytest.raises(mojang.MojangError):
        await mojang.lookup_by_name("Notch")


async def test_lookup_raises_on_timeout(monkeypatch):
    # Both endpoints time out → MojangError.
    def handler(request):
        raise httpx.ConnectTimeout("simulated")

    _patch_async_client(monkeypatch, handler)

    with pytest.raises(mojang.MojangError):
        await mojang.lookup_by_name("Notch")


async def test_lookup_url_encodes_special_characters(monkeypatch):
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(204)

    _patch_async_client(monkeypatch, handler)

    await mojang.lookup_by_name("a/b c")

    assert captured["url"] == (
        "https://api.minecraftservices.com/minecraft/profile/lookup/name/a%2Fb%20c"
    )


async def test_lookup_falls_back_on_primary_5xx(monkeypatch):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if "minecraftservices" in str(request.url):
            return httpx.Response(503, text="primary down")
        return httpx.Response(
            200,
            json={"id": "069a79f444e94726a5befca90e38aaf5", "name": "Notch"},
        )

    _patch_async_client(monkeypatch, handler)

    result = await mojang.lookup_by_name("Notch")

    assert len(calls) == 2
    assert "minecraftservices" in calls[0]
    assert "mojang" in calls[1]
    assert result == {"uuid": "069a79f4-44e9-4726-a5be-fca90e38aaf5", "name": "Notch"}


async def test_lookup_falls_back_on_primary_timeout(monkeypatch):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if "minecraftservices" in str(request.url):
            raise httpx.ConnectTimeout("simulated primary timeout")
        return httpx.Response(
            200,
            json={"id": "069a79f444e94726a5befca90e38aaf5", "name": "Notch"},
        )

    _patch_async_client(monkeypatch, handler)

    result = await mojang.lookup_by_name("Notch")

    assert len(calls) == 2
    assert "minecraftservices" in calls[0]
    assert "mojang" in calls[1]
    assert result == {"uuid": "069a79f4-44e9-4726-a5be-fca90e38aaf5", "name": "Notch"}
