"""Reconcile observed state without promoting a server before its listener is ready."""

from mcontrol.services import lifecycle_service


async def observed_state(server: dict, stats: dict) -> str | None:
    live = stats.get("container_state")
    if not live or live == server.get("state"):
        return None
    if live == "running":
        port = (server.get("variables") or {}).get("port")
        if isinstance(port, int) and not await lifecycle_service.probe_listener_once(port):
            return None
    return live
