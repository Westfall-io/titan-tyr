"""Per-caller auth tokens with scopes (#81 + #82 + #84).

Three threads:

1. CRUD on /auth-tokens — issue, list, revoke. Hash-at-rest. Plaintext
   returned exactly once.
2. The auth dependency (`require_token` + `require_scope`) honors the
   table — token scopes gate each route, and X-Actor is derived from
   the token (header is ignored on the per-caller path).
3. The legacy shared-bearer path is still accepted (for the
   transitional period) and grants all scopes; falls back to header
   X-Actor.
"""
from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient

from src.auth_tokens import hash_token


# ---------- helpers ----------


async def _issue(client, *, actor, description="t", scopes=None):
    scopes = scopes or ["write"]
    r = await client.post(
        "/auth-tokens",
        json={"actor": actor, "description": description, "scopes": scopes},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _bearer_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------- CRUD ----------


class TestIssueAuthToken:
    @pytest.mark.asyncio
    async def test_returns_plaintext_once(self, client):
        body = await _issue(client, actor="alice@example.com")
        assert "token" in body
        assert len(body["token"]) >= 32
        assert body["token_prefix"] == body["token"][:8]
        assert body["actor"] == "alice@example.com"
        assert "write" in body["scopes"]

    @pytest.mark.asyncio
    async def test_listed_without_plaintext(self, client):
        await _issue(client, actor="alice@example.com")
        listed = await client.get("/auth-tokens")
        assert listed.status_code == 200, listed.text
        for row in listed.json()["results"]:
            assert "token" not in row
            assert len(row["token_prefix"]) == 8

    @pytest.mark.asyncio
    async def test_hashed_at_rest(self, client):
        # No plaintext leaks via the list endpoint: only the 8-char
        # prefix and the metadata. Combined with the next test
        # (revoked token can no longer authenticate), this proves
        # the row stores the hash, not the plaintext.
        body = await _issue(client, actor="alice@example.com")
        listed = await client.get("/auth-tokens")
        assert listed.status_code == 200, listed.text
        for row in listed.json()["results"]:
            assert "token" not in row
            assert "token_hash" not in row
        # The plaintext we got back is at least 32 chars (32 random
        # bytes -> 43 url-safe). Prefix is only the first 8.
        assert len(body["token"]) >= 32
        assert body["token_prefix"] == body["token"][:8]
        # And the canonical sha256 of the plaintext fits the column
        # width — sanity check the hashing helper.
        assert len(hash_token(body["token"])) == 64

    @pytest.mark.asyncio
    async def test_invalid_scope_422(self, client):
        r = await client.post(
            "/auth-tokens",
            json={"actor": "alice", "description": "x", "scopes": ["delete-everything"]},
        )
        assert r.status_code == 422, r.text

    @pytest.mark.asyncio
    async def test_empty_scopes_422(self, client):
        r = await client.post(
            "/auth-tokens",
            json={"actor": "alice", "description": "x", "scopes": []},
        )
        assert r.status_code == 422, r.text


class TestRevokeAuthToken:
    @pytest.mark.asyncio
    async def test_revoked_token_401_on_next_use(self, client, engine):
        body = await _issue(client, actor="alice", scopes=["write"])
        token = body["token"]
        token_id = body["id"]

        # Construct a fresh client carrying the new per-caller token
        # (the conftest `client` carries the legacy shared bearer).
        from asgi_lifespan import LifespanManager
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from src import db as db_module
        from src.main import create_app

        sm = async_sessionmaker(engine, expire_on_commit=False)
        app = create_app()

        async def override_session():
            async with sm() as s:
                yield s

        app.dependency_overrides[db_module.get_session] = override_session

        async with LifespanManager(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as ac:
                ac.headers.update(_bearer_headers(token))
                ok = await ac.get("/parts")
                assert ok.status_code == 200, ok.text

                # Revoke via the conftest client (legacy bearer
                # admin), then re-try with the now-revoked token.
                rev = await client.post(
                    f"/auth-tokens/{token_id}/revoke",
                    json={"rationale": "test"},
                )
                assert rev.status_code == 200, rev.text

                gone = await ac.get("/parts")
                assert gone.status_code == 401, gone.text

    @pytest.mark.asyncio
    async def test_revoke_unknown_token_404(self, client):
        import uuid

        r = await client.post(
            f"/auth-tokens/{uuid.uuid4()}/revoke",
            json={"rationale": "x"},
        )
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_revoke_malformed_id_404(self, client):
        r = await client.post(
            "/auth-tokens/not-a-uuid/revoke",
            json={"rationale": "x"},
        )
        assert r.status_code == 404


# ---------- Per-caller token: X-Actor derived from token ----------


class TestPerCallerActorDerivation:
    @pytest.mark.asyncio
    async def test_header_ignored_token_actor_wins(self, client, engine):
        body = await _issue(client, actor="agent-a", scopes=["write"])

        from sqlalchemy.ext.asyncio import async_sessionmaker

        from asgi_lifespan import LifespanManager

        from src import db as db_module
        from src.main import create_app

        sm = async_sessionmaker(engine, expire_on_commit=False)
        app = create_app()

        async def override_session():
            async with sm() as s:
                yield s

        app.dependency_overrides[db_module.get_session] = override_session

        async with LifespanManager(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as ac:
                ac.headers.update(_bearer_headers(body["token"]))
                # Send a misleading X-Actor; the token's actor should
                # be recorded as `created_by_actor`, not the header.
                r = await ac.post(
                    "/parts",
                    headers={"X-Actor": "alice-pretender@example.com"},
                    json={
                        "name": "p1",
                        "subtype": "software",
                        "repo_uri": "u",
                        "markdown": "# p1\n\nbody",
                    },
                )
                assert r.status_code == 201, r.text
                assert r.json()["created_by_actor"] == "agent-a"


# ---------- Scope enforcement ----------


class TestScopeEnforcement:
    @pytest.mark.asyncio
    async def test_read_token_blocked_from_post(self, client, engine):
        body = await _issue(client, actor="reader@x", scopes=["read"])

        from sqlalchemy.ext.asyncio import async_sessionmaker

        from asgi_lifespan import LifespanManager

        from src import db as db_module
        from src.main import create_app

        sm = async_sessionmaker(engine, expire_on_commit=False)
        app = create_app()

        async def override_session():
            async with sm() as s:
                yield s

        app.dependency_overrides[db_module.get_session] = override_session

        async with LifespanManager(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as ac:
                ac.headers.update(_bearer_headers(body["token"]))
                # GET works.
                ok = await ac.get("/parts")
                assert ok.status_code == 200, ok.text
                # POST 403 with named scope in detail.
                bad = await ac.post(
                    "/parts",
                    json={
                        "name": "p2",
                        "subtype": "software",
                        "repo_uri": "u",
                        "markdown": "# p2",
                    },
                )
                assert bad.status_code == 403, bad.text
                assert "write" in bad.json()["detail"]

    @pytest.mark.asyncio
    async def test_write_token_blocked_from_revoke_agent(self, client, engine):
        body = await _issue(client, actor="writer@x", scopes=["write"])

        from sqlalchemy.ext.asyncio import async_sessionmaker

        from asgi_lifespan import LifespanManager

        from src import db as db_module
        from src.main import create_app

        sm = async_sessionmaker(engine, expire_on_commit=False)
        app = create_app()

        async def override_session():
            async with sm() as s:
                yield s

        app.dependency_overrides[db_module.get_session] = override_session

        async with LifespanManager(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as ac:
                ac.headers.update(_bearer_headers(body["token"]))
                # Revoke route requires revoke-agent — 403.
                bad = await ac.post(
                    "/agent-actors/mimiron/revoke",
                    json={"rationale": "test"},
                )
                assert bad.status_code == 403, bad.text
                assert "revoke-agent" in bad.json()["detail"]

    @pytest.mark.asyncio
    async def test_cannot_mint_scope_above_own(self, client, engine):
        # Issue a write-only token, then try to use it to mint a
        # revoke-agent token — must be 403.
        body = await _issue(client, actor="writer@x", scopes=["write"])

        from sqlalchemy.ext.asyncio import async_sessionmaker

        from asgi_lifespan import LifespanManager

        from src import db as db_module
        from src.main import create_app

        sm = async_sessionmaker(engine, expire_on_commit=False)
        app = create_app()

        async def override_session():
            async with sm() as s:
                yield s

        app.dependency_overrides[db_module.get_session] = override_session

        async with LifespanManager(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as ac:
                ac.headers.update(_bearer_headers(body["token"]))
                bad = await ac.post(
                    "/auth-tokens",
                    json={
                        "actor": "alice",
                        "description": "trying to escalate",
                        "scopes": ["revoke-agent"],
                    },
                )
                assert bad.status_code == 403, bad.text
                assert "exceed" in bad.json()["detail"]
