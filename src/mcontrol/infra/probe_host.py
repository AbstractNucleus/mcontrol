"""Which host to TCP-probe for a server's host-published port.

Inside the panel container ``127.0.0.1`` is the panel's own loopback,
so probing it for a Minecraft server's published port always refuses
(review F-3 / B2). Host-published ``0.0.0.0`` ports are reachable from
a bridge-networked container via that network's gateway, so the panel
probes its own gateway instead.

Resolution order, cached per process once a definite answer is found:

1. ``Settings.probe_host`` (env ``PROBE_HOST``) when set.
2. The gateway of the panel container's first Docker network.
3. ``127.0.0.1`` (dev_mock / bare metal, or when not running in Docker).

``resolve()`` is awaited in the lifespan so the sync ``probe_host()``
accessor is warm for callers that cannot await (``check_port_bound``).
"""

import logging

import aiodocker

from mcontrol.infra import docker_client
from mcontrol.settings import get_settings

logger = logging.getLogger(__name__)

LOOPBACK = "127.0.0.1"

_resolved: str | None = None


async def resolve(docker: aiodocker.Docker) -> str:
    """Resolve (and cache) the probe host. A daemon that cannot be
    reached yields the loopback fallback without caching, so a later
    call can still detect the gateway."""
    global _resolved
    if _resolved is not None:
        return _resolved
    configured = get_settings().probe_host
    if configured:
        _resolved = configured
        return configured
    try:
        gateway = await docker_client.self_network_gateway(docker)
    except Exception as exc:
        logger.warning("probe host: could not inspect own container (%s); using %s", exc, LOOPBACK)
        return LOOPBACK
    _resolved = gateway or LOOPBACK
    logger.info("probe host: %s (%s)", _resolved, "docker gateway" if gateway else "loopback")
    return _resolved


def probe_host() -> str:
    """Sync accessor: the resolved host, else the configured one, else loopback."""
    if _resolved is not None:
        return _resolved
    return get_settings().probe_host or LOOPBACK


def reset() -> None:
    """Forget the cached resolution (tests)."""
    global _resolved
    _resolved = None
