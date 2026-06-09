"""Integration tests for the OIDC auth arm in src/auth.py (#124).

These exercise `require_token` via real HTTP requests through the
ASGI test client, verifying that:
  - a JWT-shaped bearer with KEYCLOAK_ISSUER set takes the OIDC path
  - the OIDC path and the per-caller-token / shared-bearer paths coexist
  - the actor extracted from the JWT flows through to audit attribution
  - KEYCLOAK_ISSUER unset → JWT-shaped tokens fall through (and 401)
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from src import oidc
from src.config import get_settings


ISSUER = "https://kc.test/realms/watchervault"
AUDIENCE = "titan-tyr"
KID = "test-key-1"


def _rsa_keypair():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return priv, priv.public_key()


def _sign(priv, *, actor="alice", aud=AUDIENCE, iss=ISSUER, exp_delta=300):
    now = datetime.now(timezone.utc)
    claims = {
        "iss": iss,
        "exp": int((now + timedelta(seconds=exp_delta)).timestamp()),
        "iat": int(now.timestamp()),
        "preferred_username": actor,
        "sub": "00000000-0000-0000-0000-000000000001",
    }
    if aud is not None:
        claims["aud"] = aud
    pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return jwt.encode(claims, pem, algorithm="RS256", headers={"kid": KID})


@pytest.fixture
def oidc_on(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "keycloak_issuer", ISSUER)
    monkeypatch.setattr(settings, "keycloak_audience", AUDIENCE)
    monkeypatch.setattr(settings, "keycloak_jwks_ttl_seconds", 3600)
    oidc._reset_jwks_caches()
    yield
    oidc._reset_jwks_caches()


@pytest.fixture
def primed(oidc_on):
    """Install a deterministic keypair in the JWKS cache and yield the
    private key so tests can sign tokens."""
    priv, pub = _rsa_keypair()
    cache = oidc._get_cache(ISSUER, 3600)
    cache._keys = {KID: pub}
    cache._fetched_at = time.monotonic()
    return priv


class TestOIDCBearer:
    async def test_valid_oidc_token_accepted(self, client, primed):
        token = _sign(primed, actor="alice")
        client.headers["Authorization"] = f"Bearer {token}"
        r = await client.get("/templates/software")
        assert r.status_code == 200

    async def test_expired_oidc_token_rejected(self, client, primed):
        token = _sign(primed, exp_delta=-60)
        client.headers["Authorization"] = f"Bearer {token}"
        r = await client.get("/templates/software")
        assert r.status_code == 401

    async def test_wrong_audience_rejected(self, client, primed):
        token = _sign(primed, aud="other-service")
        client.headers["Authorization"] = f"Bearer {token}"
        r = await client.get("/templates/software")
        assert r.status_code == 401

    async def test_wrong_issuer_rejected(self, client, primed):
        token = _sign(primed, iss="https://evil.example.com/realms/x")
        client.headers["Authorization"] = f"Bearer {token}"
        r = await client.get("/templates/software")
        assert r.status_code == 401

    async def test_bad_signature_rejected(self, client, primed, monkeypatch):
        # Sign with a different key; stub refresh so the on-mismatch
        # retry doesn't hit the network.
        other_priv, _ = _rsa_keypair()
        token = _sign(other_priv)
        client.headers["Authorization"] = f"Bearer {token}"

        async def _noop_refresh(self) -> None:
            return None

        monkeypatch.setattr(oidc.JWKSCache, "_refresh", _noop_refresh)
        r = await client.get("/templates/software")
        assert r.status_code == 401

    async def test_shared_bearer_still_works_with_oidc_enabled(self, client, primed):
        # The default `client` fixture is already authed with the shared
        # bearer; primed turns OIDC on. Opaque (non-JWT-shaped) token
        # should fall through OIDC to the existing path.
        r = await client.get("/templates/software")
        assert r.status_code == 200

    async def test_jwt_shaped_token_without_oidc_falls_through(self, client):
        # No oidc_on fixture → KEYCLOAK_ISSUER stays empty. A JWT-shaped
        # bearer is not validated; it's treated as opaque and fails the
        # per-caller-token + shared-bearer lookups → 401.
        token = "header.payload.signature"
        client.headers["Authorization"] = f"Bearer {token}"
        r = await client.get("/templates/software")
        assert r.status_code == 401

    async def test_actor_resolves_from_jwt_on_writes(self, client, primed):
        # OIDC actor flows through to audit attribution. Register a
        # project under an admin-human OIDC identity and confirm the
        # owner_actor reflects the JWT's preferred_username.
        token = _sign(primed, actor="alice-admin")
        client.headers["Authorization"] = f"Bearer {token}"
        r = await client.post("/projects", json={"name": "oidc-test"})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["owner_actor"] == "alice-admin"
