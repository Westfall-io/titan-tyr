"""Auth-token issuance + listing + revoke (#81 + #82).

Mirrors the agent-actors router shape: cursor-paginated list, soft
delete via revoke. Plaintext is returned exactly once at issue
time via `AuthTokenIssueResponse.token`; subsequent list/detail
endpoints return only the prefix and metadata.

Scope rules at this surface:
- Issuance requires `write` scope. Issuer cannot mint a token with
  a scope above their own — a `write` token can issue read or write
  tokens but not `revoke-agent`.
- Listing requires `read`.
- Revoke requires `revoke-agent` (matches the agent-actors revoke
  pattern; the bar for invalidating a peer's credential is the
  highest scope today).
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import current_actor, require_scope, require_token
from src.auth_tokens import mint_token
from src.db import get_session
from src.models import AuthToken
from src.pagination import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    decode_cursor,
    encode_cursor,
    validate_limit,
)
from src.schemas import (
    AuthTokenDetail,
    AuthTokenIssue,
    AuthTokenIssueResponse,
    AuthTokenListResponse,
    AuthTokenRevoke,
    expand_scopes,
)

router = APIRouter(
    prefix="/auth-tokens",
    tags=["auth-tokens"],
    dependencies=[Depends(require_token)],
)


@router.post(
    "",
    response_model=AuthTokenIssueResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_scope("write"))],
)
async def issue_auth_token(
    request: Request,
    payload: AuthTokenIssue,
    session: AsyncSession = Depends(get_session),
    issuer: str | None = Depends(current_actor),
) -> AuthTokenIssueResponse:
    # Bound the issuance: the issuer cannot mint a token whose
    # effective scope set exceeds their own. Without this, a `write`
    # holder could escalate to `revoke-agent` simply by minting a
    # new token with that scope.
    issuer_effective: frozenset[str] = getattr(
        request.state, "scopes", frozenset()
    )
    requested_effective = expand_scopes(payload.scopes)
    over: set[str] = set(requested_effective - issuer_effective)
    if over:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Cannot issue a token with scope(s) {sorted(over)} that "
                f"exceed your own ({sorted(issuer_effective)}). Have an "
                f"admin issue this token instead."
            ),
        )

    plaintext, token_hash, prefix = mint_token()
    row = AuthToken(
        token_hash=token_hash,
        token_prefix=prefix,
        actor=payload.actor,
        description=payload.description,
        scopes=sorted(set(payload.scopes)),
        issued_by_actor=issuer,
        expires_at=payload.expires_at,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return AuthTokenIssueResponse(
        id=row.id,
        actor=row.actor,
        description=row.description,
        scopes=row.scopes,
        issued_at=row.issued_at,
        issued_by_actor=row.issued_by_actor,
        expires_at=row.expires_at,
        token_prefix=row.token_prefix,
        token=plaintext,
    )


@router.get(
    "",
    response_model=AuthTokenListResponse,
    dependencies=[Depends(require_scope("read"))],
)
async def list_auth_tokens(
    actor: str | None = Query(default=None),
    after: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    include_revoked: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
) -> AuthTokenListResponse:
    limit = validate_limit(limit)

    stmt = select(AuthToken)
    if not include_revoked:
        stmt = stmt.where(AuthToken.revoked_at.is_(None))
    if actor is not None:
        stmt = stmt.where(AuthToken.actor == actor)
    if after is not None:
        cursor_t, cursor_id = decode_cursor(after)
        stmt = stmt.where(
            tuple_(AuthToken.issued_at, AuthToken.id) < tuple_(cursor_t, cursor_id)
        )
    stmt = stmt.order_by(
        AuthToken.issued_at.desc(), AuthToken.id.desc()
    ).limit(limit + 1)

    rows = (await session.execute(stmt)).scalars().all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = (
        encode_cursor(rows[-1].issued_at, rows[-1].id)
        if has_more and rows
        else None
    )
    return AuthTokenListResponse(
        results=[AuthTokenDetail.model_validate(r) for r in rows],
        next=next_cursor,
    )


@router.post(
    "/{token_id}/revoke",
    response_model=AuthTokenDetail,
    dependencies=[Depends(require_scope("revoke-agent"))],
)
async def revoke_auth_token(
    token_id: str,
    payload: AuthTokenRevoke,
    session: AsyncSession = Depends(get_session),
    revoker: str | None = Depends(current_actor),
) -> AuthTokenDetail:
    import uuid as _uuid

    try:
        tid = _uuid.UUID(token_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Auth token {token_id!r} not found",
        )

    row = (
        await session.execute(
            select(AuthToken)
            .where(
                AuthToken.id == tid,
                AuthToken.revoked_at.is_(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Auth token {token_id!r} is not currently active",
        )
    row.revoked_at = datetime.now(timezone.utc)
    row.revoked_by_actor = revoker
    row.revoke_rationale = payload.rationale
    await session.commit()
    await session.refresh(row)
    return AuthTokenDetail.model_validate(row)
