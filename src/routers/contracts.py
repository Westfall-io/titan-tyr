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
    CONNECTION_TYPES,
    CONTRACT_SUBTYPES,
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

# Per-label From/To Part subtype rules for connection contracts (#32).
# `allowed_owner` / `allowed_counterparty` are sets of allowed subtype
# strings. Subtype strings referenced here that don't yet exist as Part
# subtypes (today: 'image', 'pod', 'compose') are detected at registration
# and rejected with a "not yet implemented" error rather than silently
# 404'ing on the part lookup.
_PART_SUBTYPES_IMPLEMENTED: set[str] = {"software", "container"}

CONNECTION_RULES: dict[str, dict[str, set[str]]] = {
    "builds-from":  {"owner": {"software"},          "counterparty": {"image"}},
    "instantiates": {"owner": {"image"},             "counterparty": {"container", "pod"}},
    "runs":         {"owner": {"container", "pod"},  "counterparty": {"software"}},
    "member-of":    {"owner": {"container"},         "counterparty": {"compose"}},
    "depends-on":   {"owner": {"container"},         "counterparty": {"container"}},
    "submodule":    {"owner": {"software"},          "counterparty": {"software"}},
}


def _check_part_subtype_implemented(
    role: str, part_name: str, required: set[str]
) -> None:
    """422 if the rule requires a Part subtype that isn't implemented yet.

    `required` is the rule's allow-set for the role; if every allowed
    subtype is unimplemented, surface a clear 'not yet implemented'
    error citing the missing subtypes.
    """
    unimplemented = required - _PART_SUBTYPES_IMPLEMENTED
    if unimplemented and not (required & _PART_SUBTYPES_IMPLEMENTED):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"this connection_type requires {role}_part subtype in "
                f"{sorted(unimplemented)}, which is not yet implemented; "
                f"see #32 for the deferred Part subtype tracking issues"
            ),
        )


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

    # `connection_type` is required iff subtype == 'connection'. Pre-validate
    # at the router layer so the user gets a clear message; the DB CHECK
    # constraint is a backstop.
    if payload.subtype == "connection" and payload.connection_type is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="connection_type is required when subtype='connection'",
        )
    if payload.subtype != "connection" and payload.connection_type is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"connection_type is only valid when subtype='connection'; "
                f"got subtype={payload.subtype!r}"
            ),
        )

    owner = await _resolve_part(session, payload.owner_part)
    counterparty = await _resolve_part(session, payload.counterparty_part)

    # Subtype-specific source/target enforcement.
    # - `interaction` accepts any (part, part) pair (no rule to apply).
    # - `binding` enforces container → software (existing behaviour).
    # - `connection` enforces per-label rules from CONNECTION_RULES, and
    #   surfaces a deferred-subtype error early when the rule references
    #   Part subtypes that aren't implemented yet.
    if payload.subtype == "binding":
        if owner.subtype != "container":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"binding contracts require owner_part subtype 'container'; "
                    f"{owner.name!r} is {owner.subtype!r}"
                ),
            )
        if counterparty.subtype != "software":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"binding contracts require counterparty_part subtype 'software'; "
                    f"{counterparty.name!r} is {counterparty.subtype!r}"
                ),
            )
    elif payload.subtype == "connection":
        rule = CONNECTION_RULES[payload.connection_type]
        _check_part_subtype_implemented("owner", owner.name, rule["owner"])
        _check_part_subtype_implemented(
            "counterparty", counterparty.name, rule["counterparty"]
        )
        if owner.subtype not in rule["owner"]:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"connection_type {payload.connection_type!r} requires "
                    f"owner_part subtype in {sorted(rule['owner'])}; "
                    f"{owner.name!r} is {owner.subtype!r}"
                ),
            )
        if counterparty.subtype not in rule["counterparty"]:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"connection_type {payload.connection_type!r} requires "
                    f"counterparty_part subtype in {sorted(rule['counterparty'])}; "
                    f"{counterparty.name!r} is {counterparty.subtype!r}"
                ),
            )

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
        subtype=payload.subtype,
        connection_type=payload.connection_type,
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
        subtype=payload.subtype,
        connection_type=payload.connection_type,
        version=str(version),
        status="active",
    )


@router.get("", response_model=Union[ContractSearchResponse, ContractListResponse])
async def list_or_search_contracts(
    owner: str | None = Query(default=None),
    counterparty: str | None = Query(default=None),
    subtype: str | None = Query(default=None),
    connection_type: str | None = Query(default=None),
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

    if subtype is not None and subtype not in CONTRACT_SUBTYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"subtype must be one of {sorted(CONTRACT_SUBTYPES)}; got {subtype!r}"
            ),
        )

    if connection_type is not None:
        if connection_type not in CONNECTION_TYPES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"connection_type must be one of {sorted(CONNECTION_TYPES)}; "
                    f"got {connection_type!r}"
                ),
            )
        if subtype is not None and subtype != "connection":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "connection_type filter is only valid with subtype='connection'; "
                    f"got subtype={subtype!r}"
                ),
            )

    if owner is None:
        # List mode: paginated summary of every contract with an active version.
        limit = validate_limit(limit)
        items, next_cursor = await _list_active_contracts(
            session,
            after=after,
            limit=limit,
            touching_part_id=None,
            subtype=subtype,
            connection_type=connection_type,
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
    if subtype is not None:
        stmt = stmt.where(Contract.subtype == subtype)
    if connection_type is not None:
        stmt = stmt.where(Contract.connection_type == connection_type)
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
                subtype=c.subtype,
                connection_type=c.connection_type,
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
        subtype=contract.subtype,
        connection_type=contract.connection_type,
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
