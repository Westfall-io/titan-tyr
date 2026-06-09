"""Unit tests for src/oidc.py — JWT validator + JWKS cache (#124)."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from src import oidc
from src.config import get_settings


ISSUER = "https://kc.test/realms/watchervault"
AUDIENCE = "titan-tyr"
KID = "test-key-1"


def _rsa_keypair() -> tuple[rsa.RSAPrivateKey, rsa.RSAPublicKey]:
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return priv, priv.public_key()


def _make_jwt(
    priv: rsa.RSAPrivateKey,
    *,
    kid: str = KID,
    issuer: str = ISSUER,
    audience: str | list[str] | None = AUDIENCE,
    actor: str = "alice",
    exp_delta_seconds: int = 300,
    extra_claims: dict | None = None,
    alg: str = "RS256",
) -> str:
    now = datetime.now(timezone.utc)
    claims: dict = {
        "iss": issuer,
        "exp": int((now + timedelta(seconds=exp_delta_seconds)).timestamp()),
        "iat": int(now.timestamp()),
        "preferred_username": actor,
        "sub": "00000000-0000-0000-0000-000000000001",
    }
    if audience is not None:
        claims["aud"] = audience
    if extra_claims:
        claims.update(extra_claims)
    pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return jwt.encode(claims, pem, algorithm=alg, headers={"kid": kid})


@pytest.fixture
def oidc_enabled(monkeypatch):
    """Flip the OIDC switch on the cached Settings object for one test."""
    settings = get_settings()
    monkeypatch.setattr(settings, "keycloak_issuer", ISSUER)
    monkeypatch.setattr(settings, "keycloak_audience", AUDIENCE)
    monkeypatch.setattr(settings, "keycloak_jwks_ttl_seconds", 3600)
    oidc._reset_jwks_caches()
    yield
    oidc._reset_jwks_caches()


@pytest.fixture
def keypair():
    return _rsa_keypair()


@pytest.fixture
def primed_cache(keypair, oidc_enabled):
    """Pre-populate the JWKS cache with our test public key so the
    validator never makes a real network call."""
    priv, pub = keypair
    cache = oidc._get_cache(ISSUER, 3600)
    cache._keys = {KID: pub}
    cache._fetched_at = time.monotonic()
    return cache


class TestLooksLikeJWT:
    def test_three_segments_passes(self):
        assert oidc.looks_like_jwt("aaa.bbb.ccc") is True

    def test_two_segments_fails(self):
        assert oidc.looks_like_jwt("aaa.bbb") is False

    def test_four_segments_fails(self):
        assert oidc.looks_like_jwt("aaa.bbb.ccc.ddd") is False

    def test_empty_segment_fails(self):
        assert oidc.looks_like_jwt("aaa..ccc") is False

    def test_opaque_token_fails(self):
        # Per-caller tokens are url-safe base64 without dots.
        assert oidc.looks_like_jwt("RR-nGaak_8C7PBWi6Gho5P6RrZbdt9Cl1kysCJSu3YM") is False


class TestValidateOIDCToken:
    async def test_valid_token_returns_preferred_username(self, keypair, primed_cache):
        priv, _ = keypair
        token = _make_jwt(priv, actor="alice")
        actor = await oidc.validate_oidc_token(token)
        assert actor == "alice"

    async def test_falls_back_to_sub_when_preferred_username_missing(
        self, keypair, primed_cache
    ):
        priv, _ = keypair
        now = datetime.now(timezone.utc)
        claims = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "exp": int((now + timedelta(seconds=300)).timestamp()),
            "sub": "abc-123",
        }
        pem = priv.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        token = jwt.encode(claims, pem, algorithm="RS256", headers={"kid": KID})
        actor = await oidc.validate_oidc_token(token)
        assert actor == "abc-123"

    async def test_expired_token_rejected(self, keypair, primed_cache):
        priv, _ = keypair
        token = _make_jwt(priv, exp_delta_seconds=-60)
        with pytest.raises(HTTPException) as exc:
            await oidc.validate_oidc_token(token)
        assert exc.value.status_code == 401

    async def test_wrong_audience_rejected(self, keypair, primed_cache):
        priv, _ = keypair
        token = _make_jwt(priv, audience="not-titan-tyr")
        with pytest.raises(HTTPException) as exc:
            await oidc.validate_oidc_token(token)
        assert exc.value.status_code == 401

    async def test_wrong_issuer_rejected(self, keypair, primed_cache):
        priv, _ = keypair
        token = _make_jwt(priv, issuer="https://evil.example.com/realms/x")
        with pytest.raises(HTTPException) as exc:
            await oidc.validate_oidc_token(token)
        assert exc.value.status_code == 401

    async def test_bad_signature_rejected(self, keypair, primed_cache, monkeypatch):
        # Sign with a different key than the one in the cache. Stub out
        # the refresh-on-signature-failure retry so we don't try to fetch
        # over the network.
        other_priv, _ = _rsa_keypair()
        token = _make_jwt(other_priv)

        async def _noop_refresh(self) -> None:
            return None

        monkeypatch.setattr(oidc.JWKSCache, "_refresh", _noop_refresh)
        with pytest.raises(HTTPException) as exc:
            await oidc.validate_oidc_token(token)
        assert exc.value.status_code == 401

    async def test_missing_kid_rejected(self, keypair, primed_cache):
        priv, _ = keypair
        now = datetime.now(timezone.utc)
        claims = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "exp": int((now + timedelta(seconds=300)).timestamp()),
            "preferred_username": "alice",
        }
        pem = priv.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        token = jwt.encode(claims, pem, algorithm="RS256")  # no headers={"kid": ...}
        with pytest.raises(HTTPException) as exc:
            await oidc.validate_oidc_token(token)
        assert exc.value.status_code == 401

    async def test_malformed_jwt_rejected(self, oidc_enabled):
        with pytest.raises(HTTPException) as exc:
            await oidc.validate_oidc_token("not-a-real-jwt")
        assert exc.value.status_code == 401


class TestJWKSCache:
    async def test_refresh_called_on_unknown_kid(self, keypair, oidc_enabled, monkeypatch):
        priv, pub = keypair
        cache = oidc._get_cache(ISSUER, 3600)
        refresh_calls = {"n": 0}

        async def _fake_refresh(self) -> None:
            refresh_calls["n"] += 1
            self._keys = {KID: pub}
            self._fetched_at = time.monotonic()

        monkeypatch.setattr(oidc.JWKSCache, "_refresh", _fake_refresh)
        key = await cache.get_key(KID)
        assert key is pub
        assert refresh_calls["n"] == 1

    async def test_refresh_skipped_within_ttl(self, keypair, oidc_enabled, monkeypatch):
        _, pub = keypair
        cache = oidc._get_cache(ISSUER, 3600)
        cache._keys = {KID: pub}
        cache._fetched_at = time.monotonic()
        refresh_calls = {"n": 0}

        async def _fake_refresh(self) -> None:
            refresh_calls["n"] += 1

        monkeypatch.setattr(oidc.JWKSCache, "_refresh", _fake_refresh)
        await cache.get_key(KID)
        assert refresh_calls["n"] == 0

    async def test_refresh_called_after_ttl_expiry(self, keypair, oidc_enabled, monkeypatch):
        _, pub = keypair
        cache = oidc._get_cache(ISSUER, 1)
        cache._keys = {KID: pub}
        cache._fetched_at = time.monotonic() - 10  # past TTL
        refresh_calls = {"n": 0}

        async def _fake_refresh(self) -> None:
            refresh_calls["n"] += 1
            self._fetched_at = time.monotonic()

        monkeypatch.setattr(oidc.JWKSCache, "_refresh", _fake_refresh)
        await cache.get_key(KID)
        assert refresh_calls["n"] == 1

    async def test_force_refresh_bypasses_cache(self, keypair, oidc_enabled, monkeypatch):
        _, pub = keypair
        cache = oidc._get_cache(ISSUER, 3600)
        cache._keys = {KID: pub}
        cache._fetched_at = time.monotonic()
        refresh_calls = {"n": 0}

        async def _fake_refresh(self) -> None:
            refresh_calls["n"] += 1

        monkeypatch.setattr(oidc.JWKSCache, "_refresh", _fake_refresh)
        await cache.get_key(KID, force_refresh=True)
        assert refresh_calls["n"] == 1
