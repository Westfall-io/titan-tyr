from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from src import db as db_module
from src.main import create_app


class TestHealth:
    async def test_returns_200_when_db_reachable(self, client):
        client.headers.pop("Authorization", None)
        r = await client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["db"] == "reachable"
        assert body["version"]  # non-empty version string

    async def test_does_not_require_bearer(self, client):
        client.headers.pop("Authorization", None)
        r = await client.get("/health")
        assert r.status_code == 200

    async def test_works_with_bearer_too(self, client):
        # Just because orchestrators don't carry one doesn't mean callers can't.
        r = await client.get("/health")
        assert r.status_code == 200


class _BrokenSession:
    async def execute(self, *args, **kwargs):
        raise RuntimeError("simulated db outage")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


@pytest_asyncio.fixture()
async def client_with_broken_db() -> AsyncIterator[AsyncClient]:
    async def broken_session():
        yield _BrokenSession()

    app = create_app()
    app.dependency_overrides[db_module.get_session] = broken_session

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


class TestHealthDbDown:
    async def test_returns_503_when_db_unreachable(self, client_with_broken_db):
        r = await client_with_broken_db.get("/health")
        assert r.status_code == 503
        body = r.json()
        assert body["status"] == "degraded"
        assert body["db"] == "unreachable"
