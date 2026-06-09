"""OIDC bearer-token validation against a Keycloak issuer (#124).

This module is the OIDC arm of the auth dependency in `src/auth.py`. When
`KEYCLOAK_ISSUER` is configured, JWT-shaped bearers are validated here
(signature via the issuer's JWKS, plus `iss` / `aud` / `exp` claims) and
the actor is extracted from `preferred_username` (or `sub`). Per-caller
tokens continue to take the existing DB-lookup path; the two coexist.

The JWKS is fetched once per issuer and cached. Cache misses (unknown
`kid` — typically Keycloak rotated keys) and TTL expiry both trigger an
async refresh.
"""

from __future__ import annotations

import asyncio
import time

import httpx
import jwt
from fastapi import HTTPException, status

from .config import get_settings


# Module-level JWKS cache, keyed by issuer URL. Tests can reset by
# calling `_reset_jwks_caches()` between cases.
_JWKS_CACHES: dict[str, "JWKSCache"] = {}


class JWKSCache:
    """Async JWKS cache.

    Holds a kid → cryptographic-key map. Refreshes on cache miss or TTL
    expiry, with an asyncio lock + double-checked condition to avoid
    redundant fetches under concurrent requests.
    """

    def __init__(self, jwks_uri: str, ttl_seconds: int) -> None:
        self._uri = jwks_uri
        self._ttl = ttl_seconds
        self._keys: dict[str, object] = {}
        self._fetched_at: float = 0.0
        self._lock = asyncio.Lock()

    async def get_key(self, kid: str, *, force_refresh: bool = False) -> object | None:
        now = time.monotonic()
        ttl_expired = (now - self._fetched_at) > self._ttl
        if force_refresh or kid not in self._keys or ttl_expired:
            await self._refresh()
        return self._keys.get(kid)

    async def _refresh(self) -> None:
        async with self._lock:
            # Another coroutine may have refreshed while we were waiting.
            if (time.monotonic() - self._fetched_at) <= self._ttl and self._keys:
                return
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(self._uri)
                resp.raise_for_status()
                jwks = resp.json()
            new_keys: dict[str, object] = {}
            for raw_jwk in jwks.get("keys", []):
                kid_value = raw_jwk.get("kid")
                if not kid_value:
                    continue
                new_keys[kid_value] = jwt.PyJWK(raw_jwk).key
            self._keys = new_keys
            self._fetched_at = time.monotonic()


def _jwks_uri_for(issuer: str) -> str:
    return f"{issuer.rstrip('/')}/protocol/openid-connect/certs"


def _get_cache(issuer: str, ttl_seconds: int) -> JWKSCache:
    cache = _JWKS_CACHES.get(issuer)
    if cache is None:
        cache = JWKSCache(_jwks_uri_for(issuer), ttl_seconds)
        _JWKS_CACHES[issuer] = cache
    return cache


def _reset_jwks_caches() -> None:
    """Test hook — clear all cached JWKS state."""
    _JWKS_CACHES.clear()


def looks_like_jwt(bearer: str) -> bool:
    """JWT shape: three non-empty base64url segments joined by `.`."""
    parts = bearer.split(".")
    return len(parts) == 3 and all(parts)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def validate_oidc_token(token: str) -> str:
    """Validate a Keycloak-issued JWT and return its actor.

    Raises 401 HTTPException on any validation failure. Returns the
    actor string on success (preferred_username, falling back to sub).
    """
    settings = get_settings()
    issuer = settings.keycloak_issuer
    audience = settings.keycloak_audience
    if not issuer:
        raise _unauthorized("OIDC validation not configured")

    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError as exc:
        raise _unauthorized(f"Malformed JWT: {exc}") from exc

    kid = header.get("kid")
    if not kid:
        raise _unauthorized("JWT header missing 'kid'")

    cache = _get_cache(issuer, settings.keycloak_jwks_ttl_seconds)
    key = await cache.get_key(kid)
    if key is None:
        # Possible key rotation since last refresh; try once more.
        key = await cache.get_key(kid, force_refresh=True)
        if key is None:
            raise _unauthorized(f"JWT signing key {kid!r} not found in JWKS")

    algorithm = header.get("alg") or "RS256"
    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=[algorithm],
            audience=audience or None,
            issuer=issuer,
            options={"require": ["exp", "iss"]},
        )
    except jwt.InvalidSignatureError:
        # Signature mismatch can also mean stale JWKS cache — refresh
        # once and retry before giving up.
        key = await cache.get_key(kid, force_refresh=True)
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=[algorithm],
                audience=audience or None,
                issuer=issuer,
                options={"require": ["exp", "iss"]},
            )
        except jwt.InvalidTokenError as exc:
            raise _unauthorized(f"OIDC validation failed: {exc}") from exc
    except jwt.InvalidTokenError as exc:
        raise _unauthorized(f"OIDC validation failed: {exc}") from exc

    actor = claims.get("preferred_username") or claims.get("sub")
    if not actor:
        raise _unauthorized("JWT missing actor claim (preferred_username/sub)")
    return str(actor)
