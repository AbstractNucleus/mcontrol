"""Mojang account-name → UUID lookup client.

Used by the slice 7 roster-add path: operator types a Minecraft
handle, mcontrol resolves it to a canonical UUID via
``GET https://api.mojang.com/users/profiles/minecraft/{name}`` and
upserts into ``app_mcontrol.players``.

Contract (decision 027 / slice 7 plan):

  - 200  → ``{"uuid": "<dashed>", "name": "<canonical-case>"}``
  - 204  → ``None`` (no Minecraft account with that name)
  - 5xx, network error, timeout → :class:`MojangError`

Other status codes are treated as ``MojangError`` rather than silently
returning ``None`` so unexpected API changes surface as failures the
operator can see, not phantom "not found" messages.
"""

from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx

_BASE_URL = "https://api.mojang.com/users/profiles/minecraft/"
_TIMEOUT_SECONDS = 5.0


class MojangError(Exception):
    """Raised when a Mojang lookup fails for a reason the operator can
    retry through (5xx, network error, timeout). The roster-add form
    surfaces this as 'Mojang lookup failed; try again'."""


async def lookup_by_name(name: str) -> dict[str, Any] | None:
    url = _BASE_URL + quote(name, safe="")
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.get(url)
    except httpx.TimeoutException as e:
        raise MojangError(f"timeout looking up {name!r}") from e
    except httpx.RequestError as e:
        raise MojangError(f"network error looking up {name!r}: {e}") from e

    if response.status_code == 204:
        return None
    if response.status_code == 200:
        body = response.json()
        return {
            "uuid": str(UUID(body["id"])),
            "name": body["name"],
        }
    if 500 <= response.status_code < 600:
        raise MojangError(f"Mojang returned {response.status_code} for {name!r}")
    raise MojangError(
        f"Mojang returned unexpected {response.status_code} for {name!r}"
    )
