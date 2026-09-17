from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from starlette.routing import Match

PageContext = Callable[[Request], Awaitable[Mapping[str, Any]]]
DashboardLifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


@dataclass(frozen=True)
class Dashboard:
    id: str
    label: str
    href: str
    icon: str
    router: APIRouter
    page_context: PageContext | None = None
    lifespan: DashboardLifespan | None = None


class DashboardRegistry:
    def __init__(self, dashboards: Iterable[Dashboard]):
        self.dashboards = tuple(dashboards)
        ids = [dashboard.id for dashboard in self.dashboards]
        if len(ids) != len(set(ids)):
            raise ValueError("dashboard ids must be unique")

    def install_routes(self, app: FastAPI) -> None:
        for dashboard in self.dashboards:
            app.include_router(dashboard.router)

    def match(self, scope: Mapping[str, Any]) -> Dashboard | None:
        partial: Dashboard | None = None
        for dashboard in self.dashboards:
            for route in dashboard.router.routes:
                route_match, _ = route.matches(dict(scope))
                if route_match is Match.FULL:
                    return dashboard
                if route_match is Match.PARTIAL and partial is None:
                    partial = dashboard
        return partial

    @asynccontextmanager
    async def lifespan(self, app: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            for dashboard in self.dashboards:
                if dashboard.lifespan is not None:
                    await stack.enter_async_context(dashboard.lifespan(app))
            yield
