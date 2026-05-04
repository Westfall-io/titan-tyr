from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Union

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import and_, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import require_password
from src.db import get_session
from src.models import Contract, ContractSubtypeProposal, ContractVersion, Part
from src.pagination import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    decode_cursor,
    encode_cursor,
    validate_limit,
)
from src.routers._rules import BINDING_OWNER_SUBTYPES, CONNECTION_RULES
from src.routers._subtype_helpers import (
    body_realign_required,
    enforce_two_party,
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
    ContractSubtypeShiftAcceptResponse,
    ContractSubtypeShiftCreate,
    ContractSubtypeShiftCreateResponse,
    ContractSubtypeShiftEntry,
    ContractSubtypeShiftListResponse,
    SubtypeShiftImpact,
    VersionHistoryItem,
    VersionHistoryResponse,
)
from src.versioning import Version

router = APIRouter(prefix="/contracts", tags=["contracts"], dependencies=[Depends(require_password)])

# With #37 every Part subtype referenced by CONNECTION_RULES is
# implemented; the deferred-subtype check below is now a no-op for the
# current rule set, but stays in place as a guard for any future rule
# that references a not-yet-implemented subtype.
_PART_SUBTYPES_IMPLEMENTED: set[str] = {
    "software", "container", "image", "pod", "compose",
}

# CONNECTION_RULES and BINDING_OWNER_SUBTYPES live in `_rules.py`
# (#33) so the parts router can also consult them for subtype-shift
# impact previews without creating a circular import. Aliased here
# for in-module readability.
_BINDING_OWNER_SUBTYPES = BINDING_OWNER_SUBTYPES


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
    x_actor: str | None = Header(default=None, alias="X-Actor"),
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
    # - `binding` enforces (container or pod) → software. The pod arm
    #   was always allowed by the SysMLv2 spec; it became reachable
    #   when `pod` landed as a Part subtype in #36.
    # - `connection` enforces per-label rules from CONNECTION_RULES, and
    #   surfaces a deferred-subtype error early when the rule references
    #   Part subtypes that aren't implemented yet.
    if payload.subtype == "binding":
        if owner.subtype not in _BINDING_OWNER_SUBTYPES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"binding contracts require owner_part subtype in "
                    f"{list(_BINDING_OWNER_SUBTYPES)}; "
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

    # Subtype-aware existence check matching the DB key from #42. The
    # connection_type comparison uses `is_(...)` so it translates to
    # `IS NULL` when payload.connection_type is None (interaction +
    # binding subtypes), which lines up with NULLS NOT DISTINCT on the
    # underlying unique index.
    existing = (
        await session.execute(
            select(Contract.id).where(
                Contract.owner_part_id == owner.id,
                Contract.counterparty_part_id == counterparty.id,
                Contract.subtype == payload.subtype,
                Contract.connection_type.is_(payload.connection_type)
                if payload.connection_type is None
                else Contract.connection_type == payload.connection_type,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        ct_suffix = (
            f"/{payload.connection_type}" if payload.connection_type else ""
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Contract from {owner.name!r} to {counterparty.name!r} "
                f"with subtype {payload.subtype!r}{ct_suffix} already exists"
            ),
        )

    contract = Contract(
        owner_part_id=owner.id,
        counterparty_part_id=counterparty.id,
        subtype=payload.subtype,
        connection_type=payload.connection_type,
        created_by_actor=x_actor,
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
                created_by_actor=c.created_by_actor,
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
        created_by_actor=contract.created_by_actor,
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
    body_rows = (
        await session.execute(
            select(
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
        )
    ).all()

    shift_rows = (
        await session.execute(
            select(
                ContractSubtypeProposal.id,
                ContractSubtypeProposal.accepted_at,
            ).where(
                ContractSubtypeProposal.contract_id == contract_id,
                ContractSubtypeProposal.status == "accepted",
            )
        )
    ).all()

    body_sorted = sorted(body_rows, key=lambda r: r.accepted_at or r.created_at)

    def _version_at(t: datetime) -> str:
        latest = None
        for r in body_sorted:
            ts = r.accepted_at or r.created_at
            if ts <= t:
                latest = r
            else:
                break
        if latest is None:
            return "0.0.0"
        return str(
            Version(latest.version_major, latest.version_minor, latest.version_patch)
        )

    entries: list[tuple[datetime, uuid.UUID, str, str]] = []
    for r in body_rows:
        ts = r.accepted_at or r.created_at
        entries.append(
            (
                ts,
                r.id,
                "body_bump",
                str(Version(r.version_major, r.version_minor, r.version_patch)),
            )
        )
    for r in shift_rows:
        if r.accepted_at is None:
            continue
        entries.append(
            (r.accepted_at, r.id, "subtype_shift", _version_at(r.accepted_at))
        )

    entries.sort(key=lambda e: (e[0], e[1]), reverse=True)

    if after is not None:
        cursor_t, cursor_id = decode_cursor(after)
        entries = [e for e in entries if (e[0], e[1]) < (cursor_t, cursor_id)]

    has_more = len(entries) > limit
    entries = entries[:limit]

    items = [
        VersionHistoryItem(version=v, updated_at=ts, kind=k)
        for ts, _, k, v in entries
    ]
    last_t, last_id = (entries[-1][0], entries[-1][1]) if entries else (None, None)
    next_cursor = encode_cursor(last_t, last_id) if has_more and last_t else None
    return VersionHistoryResponse(results=items, next=next_cursor)


# ---------- Subtype-shift proposals (#33) ----------


def _validate_contract_shift_payload(
    *, current: Contract, payload: ContractSubtypeShiftCreate
) -> None:
    """Reject payloads that violate the connection_type required-iff rule.

    Pydantic enforces the enum membership; this enforces the
    cross-field constraint. Same shape as register_contract's
    pre-validation, but for the proposed shift's destination state.
    """
    if payload.new_subtype == "connection" and payload.new_connection_type is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="new_connection_type is required when new_subtype='connection'",
        )
    if payload.new_subtype != "connection" and payload.new_connection_type is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"new_connection_type is only valid when new_subtype='connection'; "
                f"got new_subtype={payload.new_subtype!r}"
            ),
        )

    is_noop = (
        payload.new_subtype == current.subtype
        and payload.new_connection_type == current.connection_type
    )
    if is_noop:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"no-op shift: contract is already subtype={current.subtype!r}"
                + (
                    f", connection_type={current.connection_type!r}"
                    if current.connection_type
                    else ""
                )
                + "; pick different fields or skip the proposal"
            ),
        )


def _check_contract_shift_source_target(
    *,
    owner_subtype: str,
    counterparty_subtype: str,
    new_subtype: str,
    new_connection_type: str | None,
) -> tuple[str, str | None]:
    """Validate the new subtype's source/target rule against current endpoints.

    Returns ('pass', None) on success, ('fail', message) on mismatch.
    interaction has no rule (always 'pass'). Caller decides whether
    to surface failure as 422 (propose-time hard-block) or as a
    field on the impact preview (informational).
    """
    if new_subtype == "interaction":
        return "pass", None
    if new_subtype == "binding":
        if owner_subtype not in BINDING_OWNER_SUBTYPES:
            return "fail", (
                f"binding requires owner subtype in {list(BINDING_OWNER_SUBTYPES)}; "
                f"current owner is {owner_subtype!r}"
            )
        if counterparty_subtype != "software":
            return "fail", (
                f"binding requires counterparty subtype 'software'; "
                f"current counterparty is {counterparty_subtype!r}"
            )
        return "pass", None
    # connection
    rule = CONNECTION_RULES[new_connection_type]
    if owner_subtype not in rule["owner"]:
        return "fail", (
            f"connection_type {new_connection_type!r} requires owner subtype in "
            f"{sorted(rule['owner'])}; current owner is {owner_subtype!r}"
        )
    if counterparty_subtype not in rule["counterparty"]:
        return "fail", (
            f"connection_type {new_connection_type!r} requires counterparty subtype in "
            f"{sorted(rule['counterparty'])}; current counterparty is {counterparty_subtype!r}"
        )
    return "pass", None


@router.post(
    "/{contract_id}/subtype-proposals",
    response_model=ContractSubtypeShiftCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def propose_contract_subtype_shift(
    contract_id: uuid.UUID,
    payload: ContractSubtypeShiftCreate,
    x_actor: str | None = Header(default=None, alias="X-Actor"),
    session: AsyncSession = Depends(get_session),
) -> ContractSubtypeShiftCreateResponse:
    contract = (
        await session.execute(
            select(Contract).where(Contract.id == contract_id).with_for_update()
        )
    ).scalar_one_or_none()
    if contract is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found"
        )

    _validate_contract_shift_payload(current=contract, payload=payload)

    owner = await session.get(Part, contract.owner_part_id)
    counterparty = await session.get(Part, contract.counterparty_part_id)
    validation, fail_reason = _check_contract_shift_source_target(
        owner_subtype=owner.subtype,
        counterparty_subtype=counterparty.subtype,
        new_subtype=payload.new_subtype,
        new_connection_type=payload.new_connection_type,
    )
    if validation == "fail":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"shift would violate source/target rule of new subtype: "
                f"{fail_reason}. Either shift the endpoint parts first, or "
                f"pick a different new_subtype."
            ),
        )

    latest = await _latest_active_contract_version(session, contract.id)
    body_md = latest.markdown if latest else None
    impact = SubtypeShiftImpact(
        body_realign_required=body_realign_required(body_md, payload.new_subtype),
        source_target_validation=validation,
        # Contract shifts never cascade to other rows by themselves —
        # the contract's own endpoints aren't changed by the shift,
        # and contracts don't carry inbound references from elsewhere.
        related_rows_potentially_affected=[],
    )

    proposal = ContractSubtypeProposal(
        contract_id=contract.id,
        current_subtype_at_propose=contract.subtype,
        current_connection_type_at_propose=contract.connection_type,
        new_subtype=payload.new_subtype,
        new_connection_type=payload.new_connection_type,
        rationale=payload.rationale,
        proposer_actor=x_actor,
        body_realign_required=impact.body_realign_required,
        status="proposal",
    )
    session.add(proposal)
    await session.flush()
    proposal_id = proposal.id
    await session.commit()

    return ContractSubtypeShiftCreateResponse(
        proposal_id=proposal_id,
        contract_id=contract.id,
        current_subtype=contract.subtype,
        current_connection_type=contract.connection_type,
        new_subtype=payload.new_subtype,
        new_connection_type=payload.new_connection_type,
        impact=impact,
        status="proposal",
    )


@router.get(
    "/{contract_id}/subtype-proposals",
    response_model=ContractSubtypeShiftListResponse,
)
async def list_contract_subtype_shifts(
    contract_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> ContractSubtypeShiftListResponse:
    contract = await session.get(Contract, contract_id)
    if contract is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found"
        )

    rows = (
        await session.execute(
            select(ContractSubtypeProposal)
            .where(ContractSubtypeProposal.contract_id == contract_id)
            .order_by(ContractSubtypeProposal.created_at.desc())
        )
    ).scalars().all()

    entries: list[ContractSubtypeShiftEntry] = []
    for r in rows:
        impact = SubtypeShiftImpact(
            body_realign_required=r.body_realign_required,
            # Source/target validation is a propose-time check; the
            # outcome is reflected in whether the proposal was created
            # at all (a 'fail' result 422s instead of writing a row).
            # On read we report 'pass' for any row that exists.
            source_target_validation="pass",
            related_rows_potentially_affected=[],
        )
        entries.append(
            ContractSubtypeShiftEntry(
                proposal_id=r.id,
                current_subtype=r.current_subtype_at_propose,
                current_connection_type=r.current_connection_type_at_propose,
                new_subtype=r.new_subtype,
                new_connection_type=r.new_connection_type,
                rationale=r.rationale,
                proposer_actor=r.proposer_actor,
                impact=impact,
                status=r.status,
                created_at=r.created_at,
                accepted_at=r.accepted_at,
                accepted_by=r.accepted_by,
                single_operator_override=r.single_operator_override,
            )
        )

    return ContractSubtypeShiftListResponse(
        contract_id=contract.id,
        current_subtype=contract.subtype,
        current_connection_type=contract.connection_type,
        proposals=entries,
    )


@router.post(
    "/{contract_id}/subtype-proposals/{proposal_id}/accept",
    response_model=ContractSubtypeShiftAcceptResponse,
)
async def accept_contract_subtype_shift(
    contract_id: uuid.UUID,
    proposal_id: uuid.UUID,
    x_actor: str | None = Header(default=None, alias="X-Actor"),
    single_operator: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
) -> ContractSubtypeShiftAcceptResponse:
    contract = (
        await session.execute(
            select(Contract).where(Contract.id == contract_id).with_for_update()
        )
    ).scalar_one_or_none()
    if contract is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found"
        )

    proposal = (
        await session.execute(
            select(ContractSubtypeProposal).where(
                ContractSubtypeProposal.id == proposal_id,
                ContractSubtypeProposal.contract_id == contract.id,
            )
        )
    ).scalar_one_or_none()
    if proposal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subtype-shift proposal {proposal_id} not found for contract {contract.id}",
        )
    if proposal.status != "proposal":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"proposal {proposal_id} is in status {proposal.status!r}; "
                f"only 'proposal' rows can be accepted"
            ),
        )

    enforce_two_party(
        proposer_actor=proposal.proposer_actor,
        acceptor_actor=x_actor,
        single_operator=single_operator,
    )

    # Re-validate at accept time: endpoint parts may have shifted
    # since the proposal was filed, breaking the rule that passed at
    # propose time.
    owner = await session.get(Part, contract.owner_part_id)
    counterparty = await session.get(Part, contract.counterparty_part_id)
    validation, fail_reason = _check_contract_shift_source_target(
        owner_subtype=owner.subtype,
        counterparty_subtype=counterparty.subtype,
        new_subtype=proposal.new_subtype,
        new_connection_type=proposal.new_connection_type,
    )
    if validation == "fail":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"shift can no longer apply: {fail_reason}. The endpoint "
                f"parts may have shifted since this proposal was filed; "
                f"file a fresh proposal once the endpoints are stable."
            ),
        )

    is_noop = (
        proposal.new_subtype == contract.subtype
        and proposal.new_connection_type == contract.connection_type
    )
    if is_noop:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"no-op accept: contract is already at the proposed shape "
                f"(a concurrent shift may have landed); this proposal is stale"
            ),
        )

    now = datetime.now(timezone.utc)
    shifted_from_subtype = contract.subtype
    shifted_from_connection_type = contract.connection_type
    contract.subtype = proposal.new_subtype
    contract.connection_type = proposal.new_connection_type
    contract.subtype_shifted_from = shifted_from_subtype
    contract.connection_type_shifted_from = shifted_from_connection_type
    contract.subtype_shifted_at = now
    proposal.status = "accepted"
    proposal.accepted_at = now
    proposal.accepted_by = x_actor
    proposal.single_operator_override = single_operator

    await session.commit()

    return ContractSubtypeShiftAcceptResponse(
        proposal_id=proposal.id,
        contract_id=contract.id,
        shifted_from_subtype=shifted_from_subtype,
        shifted_to_subtype=proposal.new_subtype,
        shifted_from_connection_type=shifted_from_connection_type,
        shifted_to_connection_type=proposal.new_connection_type,
        accepted_at=now,
        accepted_by=x_actor,
        body_realign_required=proposal.body_realign_required,
        single_operator_override=single_operator,
    )
