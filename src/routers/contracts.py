from __future__ import annotations

import uuid
from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import require_password
from src.db import get_session
from src.models import Contract, ContractVersion, Part
from src.pagination import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    decode_cursor,
    encode_cursor,
    validate_limit,
)
from src.routers.parts import _latest_active_contract_version, _list_active_contracts
from src.schemas import (
    ContractCreate,
    ContractCreateResponse,
    ContractDetail,
    ContractListResponse,
    ContractSearchResponse,
    ContractSearchResult,
    VersionHistoryItem,
    VersionHistoryResponse,
)
from src.versioning import Version

router = APIRouter(prefix="/contracts", tags=["contracts"], dependencies=[Depends(require_password)])


async def _resolve_part(session: AsyncSession, name: str) -> Part:
    pt = (await session.execute(select(Part).where(Part.name == name))).scalar_one_or_none()
    if pt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Part {name!r} not found")
    return pt


@router.post("", response_model=ContractCreateResponse, status_code=status.HTTP_201_CREATED)
async def register_contract(
    payload: ContractCreate,
    session: AsyncSession = Depends(get_session),
) -> ContractCreateResponse:
    if payload.owner_part == payload.counterparty_part:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="owner_part and counterparty_part must differ",
        )
    owner = await _resolve_part(session, payload.owner_part)
    counterparty = await _resolve_part(session, payload.counterparty_part)

    version = Version.parse(payload.version, allow_prerelease=False)

    existing = (
        await session.execute(
            select(Contract.id).where(
                Contract.owner_part_id == owner.id,
                Contract.counterparty_part_id == counterparty.id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Contract from {owner.name!r} to {counterparty.name!r} already exists",
        )

    contract = Contract(
        owner_part_id=owner.id,
        counterparty_part_id=counterparty.id,
    )
    session.add(contract)
    await session.flush()

    cv = ContractVersion(
        contract_id=contract.id,
        version_major=version.major,
        version_minor=version.minor,
        version_patch=version.patch,
        prerelease=None,
        markdown=payload.markdown,
        status="active",
    )
    session.add(cv)
    await session.commit()

    return ContractCreateResponse(
        contract_id=contract.id,
        owner=owner.name,
        counterparty=counterparty.name,
        version=str(version),
        status="active",
    )


@router.get("", response_model=Union[ContractSearchResponse, ContractListResponse])
async def list_or_search_contracts(
    owner: str | None = Query(default=None),
    counterparty: str | None = Query(default=None),
    after: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    session: AsyncSession = Depends(get_session),
):
    # Search mode requires both filters; list mode requires neither.
    if (owner is None) != (counterparty is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="owner and counterparty must be supplied together for search; supply neither to list.",
        )

    if owner is None:
        # List mode: paginated summary of every contract with an active version.
        limit = validate_limit(limit)
        items, next_cursor = await _list_active_contracts(
            session, after=after, limit=limit, touching_part_id=None
        )
        return ContractListResponse(results=items, next=next_cursor)

    # Search mode: existing behaviour. Up to 2 results, full markdown.
    a = await _resolve_part(session, owner)
    b = await _resolve_part(session, counterparty)

    stmt = select(Contract).where(
        or_(
            and_(
                Contract.owner_part_id == a.id,
                Contract.counterparty_part_id == b.id,
            ),
            and_(
                Contract.owner_part_id == b.id,
                Contract.counterparty_part_id == a.id,
            ),
        )
    )
    contracts = (await session.execute(stmt)).scalars().all()

    results: list[ContractSearchResult] = []
    for c in contracts:
        latest = await _latest_active_contract_version(session, c.id)
        if latest is None:
            continue
        owner_name = (await session.get(Part, c.owner_part_id)).name
        cp_name = (await session.get(Part, c.counterparty_part_id)).name
        results.append(
            ContractSearchResult(
                contract_id=c.id,
                owner=owner_name,
                counterparty=cp_name,
                version=str(Version(latest.version_major, latest.version_minor, latest.version_patch)),
                markdown=latest.markdown,
                updated_at=latest.accepted_at or latest.created_at,
            )
        )
    return ContractSearchResponse(results=results)


@router.get("/{contract_id}", response_model=ContractDetail)
async def get_contract(
    contract_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> ContractDetail:
    contract = await session.get(Contract, contract_id)
    if contract is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found")
    latest = await _latest_active_contract_version(session, contract_id)
    if latest is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contract has no active version")
    owner = (await session.get(Part, contract.owner_part_id)).name
    counterparty = (await session.get(Part, contract.counterparty_part_id)).name
    return ContractDetail(
        contract_id=contract.id,
        owner=owner,
        counterparty=counterparty,
        version=str(Version(latest.version_major, latest.version_minor, latest.version_patch)),
        markdown=latest.markdown,
        updated_at=latest.accepted_at or latest.created_at,
    )


@router.get("/{contract_id}/history", response_model=VersionHistoryResponse)
async def get_contract_history(
    contract_id: uuid.UUID,
    after: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    session: AsyncSession = Depends(get_session),
) -> VersionHistoryResponse:
    limit = validate_limit(limit)

    contract = await session.get(Contract, contract_id)
    if contract is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found")

    # Only accepted versions land in history. The active_must_be_stable check
    # constraint on contract_versions guarantees status='active' rows have a
    # NULL prerelease, so this naturally excludes superseded RC iterations.
    stmt = select(
        ContractVersion.id,
        ContractVersion.version_major,
        ContractVersion.version_minor,
        ContractVersion.version_patch,
        ContractVersion.created_at,
        ContractVersion.accepted_at,
    ).where(
        ContractVersion.contract_id == contract_id,
        ContractVersion.status == "active",
    )

    if after is not None:
        cursor_t, cursor_id = decode_cursor(after)
        stmt = stmt.where(
            tuple_(ContractVersion.created_at, ContractVersion.id)
            < tuple_(cursor_t, cursor_id)
        )

    stmt = stmt.order_by(
        ContractVersion.created_at.desc(), ContractVersion.id.desc()
    ).limit(limit + 1)

    rows = (await session.execute(stmt)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    items: list[VersionHistoryItem] = []
    last_t = None
    last_id = None
    for cv_id, vmaj, vmin, vpat, vcreated, vaccepted in rows:
        items.append(
            VersionHistoryItem(
                version=str(Version(vmaj, vmin, vpat)),
                updated_at=vaccepted or vcreated,
            )
        )
        last_t, last_id = vcreated, cv_id

    next_cursor = encode_cursor(last_t, last_id) if has_more and last_t else None
    return VersionHistoryResponse(results=items, next=next_cursor)
