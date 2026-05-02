from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src import db as db_module
from src.auth import PASSWORD
from src.db import Base
from src.main import create_app


def _container_dsn() -> str:
    """Return an asyncpg DSN, preferring TEST_DATABASE_URL or spinning up a container."""
    env_url = os.environ.get("TEST_DATABASE_URL")
    if env_url:
        return env_url
    from testcontainers.postgres import PostgresContainer

    pg = PostgresContainer("postgres:16-alpine")
    pg.start()
    pytest._titan_tyr_pg_container = pg  # keep alive for the session
    raw = pg.get_connection_url()  # postgresql+psycopg2://...
    return raw.replace("postgresql+psycopg2://", "postgresql+asyncpg://").replace(
        "postgresql://", "postgresql+asyncpg://"
    )


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    url = _container_dsn()
    yield url
    container = getattr(pytest, "_titan_tyr_pg_container", None)
    if container is not None:
        container.stop()


@pytest_asyncio.fixture()
async def engine(database_url):
    """Function-scoped engine using NullPool so each event loop gets fresh connections."""
    engine = create_async_engine(database_url, future=True, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture()
async def db_session(engine) -> AsyncIterator[AsyncSession]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        yield session


@pytest_asyncio.fixture()
async def client(engine, db_session) -> AsyncIterator[AsyncClient]:
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    app = create_app()
    app.dependency_overrides[db_module.get_session] = override_session

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            ac.headers.update({"Authorization": f"Bearer {PASSWORD}"})
            yield ac


@pytest.fixture()
def unauth_headers() -> dict[str, str]:
    return {}
