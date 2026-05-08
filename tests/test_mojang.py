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

    assert captured["url"] == "https://api.mojang.com/users/profiles/minecraft/Notch"
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
    def handler(request):
        return httpx.Response(503, text="upstream gone")

    _patch_async_client(monkeypatch, handler)

    with pytest.raises(mojang.MojangError):
        await mojang.lookup_by_name("Notch")


async def test_lookup_raises_on_timeout(monkeypatch):
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

    assert captured["url"] == "https://api.mojang.com/users/profiles/minecraft/a%2Fb%20c"
