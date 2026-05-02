from __future__ import annotations

import uuid
from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import require_password
from src.db import get_session
from src.models import Contract, ContractVersion, Software
from src.pagination import DEFAULT_LIMIT, MAX_LIMIT, validate_limit
from src.routers.software import _latest_active_contract_version, _list_active_contracts
from src.schemas import (
    ContractCreate,
    ContractCreateResponse,
    ContractDetail,
    ContractListResponse,
    ContractSearchResponse,
    ContractSearchResult,
)
from src.versioning import Version

router = APIRouter(prefix="/contracts", tags=["contracts"], dependencies=[Depends(require_password)])


async def _resolve_software(session: AsyncSession, name: str) -> Software:
    sw = (await session.execute(select(Software).where(Software.name == name))).scalar_one_or_none()
    if sw is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Software {name!r} not found")
    return sw


@router.post("", response_model=ContractCreateResponse, status_code=status.HTTP_201_CREATED)
async def register_contract(
    payload: ContractCreate,
    session: AsyncSession = Depends(get_session),
) -> ContractCreateResponse:
    if payload.owner_software == payload.counterparty_software:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="owner_software and counterparty_software must differ",
        )
    owner = await _resolve_software(session, payload.owner_software)
    counterparty = await _resolve_software(session, payload.counterparty_software)

    version = Version.parse(payload.version, allow_prerelease=False)

    existing = (
        await session.execute(
            select(Contract.id).where(
                Contract.owner_software_id == owner.id,
                Contract.counterparty_software_id == counterparty.id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Contract from {owner.name!r} to {counterparty.name!r} already exists",
        )

    contract = Contract(
        owner_software_id=owner.id,
        counterparty_software_id=counterparty.id,
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
            session, after=after, limit=limit, touching_software_id=None
        )
        return ContractListResponse(results=items, next=next_cursor)

    # Search mode: existing behaviour. Up to 2 results, full markdown.
    a = await _resolve_software(session, owner)
    b = await _resolve_software(session, counterparty)

    stmt = select(Contract).where(
        or_(
            and_(
                Contract.owner_software_id == a.id,
                Contract.counterparty_software_id == b.id,
            ),
            and_(
                Contract.owner_software_id == b.id,
                Contract.counterparty_software_id == a.id,
            ),
        )
    )
    contracts = (await session.execute(stmt)).scalars().all()

    results: list[ContractSearchResult] = []
    for c in contracts:
        latest = await _latest_active_contract_version(session, c.id)
        if latest is None:
            continue
        owner_name = (await session.get(Software, c.owner_software_id)).name
        cp_name = (await session.get(Software, c.counterparty_software_id)).name
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
    owner = (await session.get(Software, contract.owner_software_id)).name
    counterparty = (await session.get(Software, contract.counterparty_software_id)).name
    return ContractDetail(
        contract_id=contract.id,
        owner=owner,
        counterparty=counterparty,
        version=str(Version(latest.version_major, latest.version_minor, latest.version_patch)),
        markdown=latest.markdown,
        updated_at=latest.accepted_at or latest.created_at,
    )
