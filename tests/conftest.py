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
from src.models import Template, TemplateVersion

SEED_SOFTWARE_TEMPLATE = "# software template seed\n\n## Purpose\nseed body\n"
SEED_INTERACTION_TEMPLATE = "# interaction template seed\n\n## Provider obligations\nseed body\n"
SEED_CONTAINER_TEMPLATE = "# container template seed\n\n## Purpose\nseed body\n"
SEED_BINDING_TEMPLATE = "# binding template seed\n\n## Provider obligations\nseed body\n"
SEED_CONNECTION_TEMPLATE = "# connection template seed\n\n## What this connection records\nseed body\n"
SEED_IMAGE_TEMPLATE = "# image template seed\n\n## Purpose\nseed body\n"
SEED_POD_TEMPLATE = "# pod template seed\n\n## Purpose\nseed body\n"


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
        # Seed the two templates with placeholder v1.0.0 active rows so that
        # GET /templates/{kind} works out of the box, mirroring what migration
        # 0002 does in production.
        for kind, markdown in (
            ("software", SEED_SOFTWARE_TEMPLATE),
            ("container", SEED_CONTAINER_TEMPLATE),
            ("image", SEED_IMAGE_TEMPLATE),
            ("pod", SEED_POD_TEMPLATE),
            ("interaction", SEED_INTERACTION_TEMPLATE),
            ("binding", SEED_BINDING_TEMPLATE),
            ("connection", SEED_CONNECTION_TEMPLATE),
        ):
            tpl = Template(kind=kind)
            session.add(tpl)
            await session.flush()
            session.add(
                TemplateVersion(
                    template_id=tpl.id,
                    version_major=1,
                    version_minor=0,
                    version_patch=0,
                    prerelease=None,
                    markdown=markdown,
                    status="active",
                )
            )
        await session.commit()
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
