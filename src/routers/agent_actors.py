"""Agent-actor allowlist router (#78).

Replaces the hardcoded `KNOWN_AGENT_ACTORS` config default that #76
shipped. The router-layer `enforce_human_confirmation` helper consults
the live rows in this table (not config) to decide whether an
acceptor X-Actor counts as an agent — so adding or revoking an agent
identity is a runtime operation, not a redeploy.

Soft-delete semantics:
- Revoke sets `revoked_at` + actor + rationale; the row stays for
  audit. Re-registering a revoked actor creates a new live row;
  partial-on-live unique index permits this.
- An actor that's never been registered, or has been registered then
  revoked, is treated as "not an agent" by the human-confirmation
  gate — the destructive accept will go through.

Authorization on revoke is itself gated by the human-confirmation
rule: an agent can register peers (the typical onboarding path) but
cannot revoke them. Otherwise a compromised agent identity could
quietly remove its peers from the allowlist and bypass
human-confirmation on subsequent destructive flows.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import require_password
from src.db import get_session
from src.models import AgentActor
from src.pagination import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    decode_cursor,
    encode_cursor,
    validate_limit,
)
from src.routers._subtype_helpers import (
    enforce_human_confirmation,
    get_active_agent_actors,
)
from src.schemas import (
    AgentActorDetail,
    AgentActorListResponse,
    AgentActorRegister,
    AgentActorRevoke,
)

router = APIRouter(
    prefix="/agent-actors",
    tags=["agent-actors"],
    dependencies=[Depends(require_password)],
)


@router.post(
    "",
    response_model=AgentActorDetail,
    status_code=status.HTTP_201_CREATED,
)
async def register_agent_actor(
    payload: AgentActorRegister,
    session: AsyncSession = Depends(get_session),
    x_actor: str | None = Header(default=None, alias="X-Actor"),
) -> AgentActorDetail:
    existing = (
        await session.execute(
            select(AgentActor.id).where(
                AgentActor.actor == payload.actor,
                AgentActor.revoked_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Agent actor {payload.actor!r} is already registered",
        )
    row = AgentActor(
        actor=payload.actor,
        description=payload.description,
        registered_by_actor=x_actor,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return AgentActorDetail.model_validate(row)


@router.get("", response_model=AgentActorListResponse)
async def list_agent_actors(
    after: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    include_revoked: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
) -> AgentActorListResponse:
    limit = validate_limit(limit)

    stmt = select(AgentActor)
    if not include_revoked:
        stmt = stmt.where(AgentActor.revoked_at.is_(None))
    if after is not None:
        cursor_t, cursor_id = decode_cursor(after)
        stmt = stmt.where(
            tuple_(AgentActor.registered_at, AgentActor.id)
            < tuple_(cursor_t, cursor_id)
        )
    stmt = stmt.order_by(
        AgentActor.registered_at.desc(), AgentActor.id.desc()
    ).limit(limit + 1)

    rows = (await session.execute(stmt)).scalars().all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    next_cursor = (
        encode_cursor(rows[-1].registered_at, rows[-1].id)
        if has_more and rows
        else None
    )
    return AgentActorListResponse(
        results=[AgentActorDetail.model_validate(r) for r in rows],
        next=next_cursor,
    )


@router.get("/{actor}", response_model=AgentActorDetail)
async def get_agent_actor(
    actor: str,
    include_revoked: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
) -> AgentActorDetail:
    stmt = select(AgentActor).where(AgentActor.actor == actor)
    if not include_revoked:
        stmt = stmt.where(AgentActor.revoked_at.is_(None))
    # If both live and revoked rows exist for the same actor (i.e. the
    # actor was revoked then re-registered), prefer the live row.
    stmt = stmt.order_by(AgentActor.revoked_at.is_(None).desc(), AgentActor.registered_at.desc())
    row = (await session.execute(stmt)).scalars().first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent actor {actor!r} not found",
        )
    return AgentActorDetail.model_validate(row)


@router.post("/{actor}/revoke", response_model=AgentActorDetail)
async def revoke_agent_actor(
    actor: str,
    payload: AgentActorRevoke,
    session: AsyncSession = Depends(get_session),
    x_actor: str | None = Header(default=None, alias="X-Actor"),
) -> AgentActorDetail:
    # Revoke is human-only. Otherwise an agent could quietly evict its
    # peers from the allowlist and turn the human-confirmation rule
    # into a single-agent rubber stamp.
    known_agents = await get_active_agent_actors(session)
    enforce_human_confirmation(
        acceptor_actor=x_actor, known_agents=known_agents
    )

    row = (
        await session.execute(
            select(AgentActor)
            .where(
                AgentActor.actor == actor,
                AgentActor.revoked_at.is_(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent actor {actor!r} is not currently registered",
        )

    from sqlalchemy import func

    row.revoked_at = (
        await session.execute(select(func.now()))
    ).scalar_one()
    row.revoked_by_actor = x_actor
    row.revoke_rationale = payload.rationale
    await session.commit()
    await session.refresh(row)
    return AgentActorDetail.model_validate(row)
