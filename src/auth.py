"""Per-caller token auth + scope checks (#81 + #82 + #84).

Two paths through this module:

1. **Per-caller token (preferred).** The bearer is hashed (sha256)
   and looked up in `auth_tokens`. On hit, the row's `actor` and
   `scopes` are stamped onto `request.state` for downstream
   handlers; the legacy `X-Actor` header is ignored.

2. **Legacy shared bearer (back-compat, transitional).** The bearer
   is compared against `Settings.bearer_password` (env-loaded; empty
   default → all rejected, so the legacy path is fail-closed unless
   a deployer opts in by setting `TITAN_TYR_BEARER_PASSWORD`). On
   hit, the request is granted ALL scopes and `request.state.actor`
   comes from the `X-Actor` header (current behavior).

Routers use one or both of:
- `Depends(require_token)` at router level: enforces auth and
  populates `request.state`.
- `Depends(require_scope("read"|"write"|"revoke-agent"))` at
  route level: 403 if the caller's scopes don't include it.

Per-handler X-Actor reads should use `Depends(current_actor)`
instead of `Header(alias="X-Actor")` so the per-caller-token path
correctly overrides any header the client sends.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth_tokens import constant_time_eq, hash_token
from src.config import get_settings
from src.db import get_session
from src.models import AuthToken
from src.schemas import AUTH_TOKEN_SCOPES, expand_scopes

_bearer = HTTPBearer(auto_error=False)

# Effective scope set granted to the legacy shared-bearer path.
# Back-compat: pre-#81 code assumed full access on a valid bearer.
# Equivalent to `expand_scopes(["revoke-agent"])` but spelled out so
# a future scope addition prompts a deliberate review.
_LEGACY_SCOPES: frozenset[str] = frozenset(AUTH_TOKEN_SCOPES)


async def require_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    x_actor_header: str | None = Header(default=None, alias="X-Actor"),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Authenticate the request and stamp actor + scopes onto request.state.

    Try per-caller-token lookup first; fall back to the legacy
    shared-bearer comparison only if the env var is set. 401 on
    miss, 401 with reason on revoked/expired.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    bearer = credentials.credentials

    # Per-caller token path. Hash + index lookup; partial-on-live
    # index ensures revoked rows can't match.
    row = (
        await session.execute(
            select(AuthToken).where(
                AuthToken.token_hash == hash_token(bearer),
                AuthToken.revoked_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        if row.expires_at is not None:
            now = datetime.now(timezone.utc)
            if row.expires_at <= now:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token expired",
                    headers={"WWW-Authenticate": "Bearer"},
                )
        request.state.actor = row.actor
        request.state.scopes = expand_scopes(row.scopes)
        request.state.token_id = row.id
        # Best-effort last_used_at touch. Errors here mustn't fail
        # the auth check, so swallow and move on.
        try:
            await session.execute(
                update(AuthToken)
                .where(AuthToken.id == row.id)
                .values(last_used_at=datetime.now(timezone.utc))
            )
            await session.commit()
        except Exception:
            await session.rollback()
        return

    # Legacy shared-bearer path. Off by default — env-loaded value
    # of empty string fails closed.
    legacy = get_settings().bearer_password
    if legacy and constant_time_eq(bearer, legacy):
        request.state.actor = x_actor_header
        request.state.scopes = _LEGACY_SCOPES
        request.state.token_id = None
        return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_scope(needed: str):
    """Dependency factory: 403 if the request's effective scopes don't include `needed`.

    Usage at the route level:

        @router.post("", dependencies=[Depends(require_scope("write"))])

    `require_token` must already have run (typically wired at the
    router level via `dependencies=[Depends(require_token)]`).
    """
    if needed not in AUTH_TOKEN_SCOPES:
        raise ValueError(
            f"require_scope: unknown scope {needed!r}; "
            f"allowed {list(AUTH_TOKEN_SCOPES)}"
        )

    def _dep(request: Request) -> None:
        scopes: frozenset[str] = getattr(request.state, "scopes", frozenset())
        if needed not in scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"This endpoint requires the {needed!r} scope; "
                    f"your token has {sorted(scopes)}. Have an admin "
                    f"issue you a token with {needed!r}."
                ),
            )

    return _dep


def current_actor(request: Request) -> str | None:
    """Return the actor identity for this request.

    Per-caller token: the row's `actor`. Legacy bearer: the X-Actor
    header value. None when unset.

    Route handlers should use `Depends(current_actor)` instead of
    reading the X-Actor header directly so the per-caller-token
    path's actor-derivation is honored.
    """
    return getattr(request.state, "actor", None)
