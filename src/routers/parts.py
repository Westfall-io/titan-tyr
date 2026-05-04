from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import require_password
from src.db import get_session
from src.models import (
    Contract,
    ContractVersion,
    Part,
    PartSubtypeProposal,
    PartVersion,
)
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
from src.schemas import (
    PART_SUBTYPES,
    ContractListItem,
    PartContractsListResponse,
    PartCreate,
    PartCreateResponse,
    PartDetail,
    PartListItem,
    PartListResponse,
    PartSubtypeShiftAcceptResponse,
    PartSubtypeShiftCreate,
    PartSubtypeShiftCreateResponse,
    PartSubtypeShiftEntry,
    PartSubtypeShiftListResponse,
    PartUpdate,
    PartUpdateResponse,
    RelatedRowAffected,
    SubtypeShiftImpact,
    VersionHistoryItem,
    VersionHistoryResponse,
)
from src.versioning import Version

router = APIRouter(prefix="/parts", tags=["parts"], dependencies=[Depends(require_password)])


async def _latest_part_version(session: AsyncSession, part_id) -> PartVersion | None:
    stmt = (
        select(PartVersion)
        .where(PartVersion.part_id == part_id)
        .order_by(
            PartVersion.version_major.desc(),
            PartVersion.version_minor.desc(),
            PartVersion.version_patch.desc(),
        )
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


@router.get("", response_model=PartListResponse)
async def list_parts(
    after: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    match: str | None = Query(default=None, max_length=128),
    subtype: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> PartListResponse:
    limit = validate_limit(limit)

    if subtype is not None and subtype not in PART_SUBTYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"subtype must be one of {sorted(PART_SUBTYPES)}",
        )

    latest_versions = (
        select(
            PartVersion.part_id.label("pv_part_id"),
            PartVersion.version_major.label("pv_major"),
            PartVersion.version_minor.label("pv_minor"),
            PartVersion.version_patch.label("pv_patch"),
            PartVersion.created_at.label("pv_created_at"),
        )
        .distinct(PartVersion.part_id)
        .order_by(
            PartVersion.part_id,
            PartVersion.version_major.desc(),
            PartVersion.version_minor.desc(),
            PartVersion.version_patch.desc(),
        )
        .subquery()
    )

    stmt = select(
        Part.id,
        Part.name,
        Part.subtype,
        Part.repo_uri,
        Part.issue_tracker_uri,
        Part.aliases,
        Part.created_by_actor,
        latest_versions.c.pv_major,
        latest_versions.c.pv_minor,
        latest_versions.c.pv_patch,
        latest_versions.c.pv_created_at,
    ).join(latest_versions, Part.id == latest_versions.c.pv_part_id)

    if subtype is not None:
        stmt = stmt.where(Part.subtype == subtype)

    if match is not None:
        # Case-insensitive substring match against name OR any alias. The U+001F
        # separator can't appear inside an alias (control chars are banned at
        # validation), so flattening the array for ILIKE is unambiguous.
        # Escape ILIKE wildcards in user input so "100%" searches literally.
        escaped = match.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        stmt = stmt.where(
            or_(
                Part.name.ilike(pattern, escape="\\"),
                func.array_to_string(Part.aliases, "\x1f").ilike(
                    pattern, escape="\\"
                ),
            )
        )

    if after is not None:
        cursor_t, cursor_id = decode_cursor(after)
        stmt = stmt.where(
            tuple_(latest_versions.c.pv_created_at, Part.id)
            < tuple_(cursor_t, cursor_id)
        )

    stmt = stmt.order_by(
        latest_versions.c.pv_created_at.desc(), Part.id.desc()
    ).limit(limit + 1)

    rows = (await session.execute(stmt)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    items: list[PartListItem] = []
    last_t = None
    last_id = None
    for (
        p_id, p_name, p_subtype, p_repo, p_tracker, p_aliases, p_creator,
        vmaj, vmin, vpat, vts,
    ) in rows:
        items.append(
            PartListItem(
                id=p_id,
                name=p_name,
                subtype=p_subtype,
                repo_uri=p_repo,
                issue_tracker_uri=p_tracker,
                aliases=list(p_aliases or []),
                version=str(Version(vmaj, vmin, vpat)),
                updated_at=vts,
                created_by_actor=p_creator,
            )
        )
        last_t, last_id = vts, p_id

    next_cursor = encode_cursor(last_t, last_id) if has_more and last_t else None
    return PartListResponse(results=items, next=next_cursor)


@router.post("", response_model=PartCreateResponse, status_code=status.HTTP_201_CREATED)
async def register_part(
    payload: PartCreate,
    session: AsyncSession = Depends(get_session),
    x_actor: str | None = Header(default=None, alias="X-Actor"),
) -> PartCreateResponse:
    version = Version.parse(payload.version, allow_prerelease=False)
    existing = (
        await session.execute(select(Part.id).where(Part.name == payload.name))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Part {payload.name!r} already exists",
        )
    part = Part(
        name=payload.name,
        subtype=payload.subtype,
        repo_uri=payload.repo_uri,
        issue_tracker_uri=payload.issue_tracker_uri,
        aliases=payload.aliases,
        created_by_actor=x_actor,
    )
    session.add(part)
    await session.flush()
    pv = PartVersion(
        part_id=part.id,
        version_major=version.major,
        version_minor=version.minor,
        version_patch=version.patch,
        markdown=payload.markdown,
    )
    session.add(pv)
    await session.commit()
    return PartCreateResponse(
        id=part.id,
        name=part.name,
        subtype=part.subtype,
        version=str(version),
    )


@router.get("/{name}", response_model=PartDetail)
async def get_part(
    name: str,
    session: AsyncSession = Depends(get_session),
) -> PartDetail:
    part = (
        await session.execute(select(Part).where(Part.name == name))
    ).scalar_one_or_none()
    if part is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Part {name!r} not found")
    latest = await _latest_part_version(session, part.id)
    if latest is None:  # invariant: every part row has at least one version
        raise HTTPException(status_code=500, detail="Part has no versions")
    version = Version(latest.version_major, latest.version_minor, latest.version_patch)
    return PartDetail(
        id=part.id,
        name=part.name,
        subtype=part.subtype,
        repo_uri=part.repo_uri,
        issue_tracker_uri=part.issue_tracker_uri,
        aliases=list(part.aliases or []),
        version=str(version),
        markdown=latest.markdown,
        updated_at=latest.created_at,
        created_by_actor=part.created_by_actor,
    )


@router.put("/{name}", response_model=PartUpdateResponse)
async def update_part(
    name: str,
    payload: PartUpdate,
    session: AsyncSession = Depends(get_session),
) -> PartUpdateResponse:
    part = (
        await session.execute(
            select(Part).where(Part.name == name).with_for_update()
        )
    ).scalar_one_or_none()
    if part is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Part {name!r} not found")

    new_version = Version.parse(payload.version, allow_prerelease=False)
    latest = await _latest_part_version(session, part.id)
    if latest is not None:
        latest_v = Version(latest.version_major, latest.version_minor, latest.version_patch)
        if not (new_version > latest_v):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Version {new_version} is not strictly greater than the current latest {latest_v}",
            )

    # PATCH semantics on row-level metadata fields. Absent = unchanged.
    # repo_uri rejects null at the schema layer (required, can't be cleared);
    # issue_tracker_uri allows null to clear; aliases treats null as clear
    # (collapse to []). Subtype is intentionally not mutable on update — a
    # part's kind is structural, not a content field; if you want a different
    # subtype, register a new part.
    if "repo_uri" in payload.model_fields_set:
        part.repo_uri = payload.repo_uri
    if "issue_tracker_uri" in payload.model_fields_set:
        part.issue_tracker_uri = payload.issue_tracker_uri
    if "aliases" in payload.model_fields_set:
        part.aliases = payload.aliases or []

    pv = PartVersion(
        part_id=part.id,
        version_major=new_version.major,
        version_minor=new_version.minor,
        version_patch=new_version.patch,
        markdown=payload.markdown,
    )
    session.add(pv)
    await session.commit()
    return PartUpdateResponse(name=part.name, version=str(new_version))


@router.get("/{name}/history", response_model=VersionHistoryResponse)
async def get_part_history(
    name: str,
    after: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    session: AsyncSession = Depends(get_session),
) -> VersionHistoryResponse:
    limit = validate_limit(limit)

    part = (
        await session.execute(select(Part.id).where(Part.name == name))
    ).scalar_one_or_none()
    if part is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Part {name!r} not found")

    body_rows = (
        await session.execute(
            select(
                PartVersion.id,
                PartVersion.version_major,
                PartVersion.version_minor,
                PartVersion.version_patch,
                PartVersion.created_at,
            ).where(PartVersion.part_id == part)
        )
    ).all()

    shift_rows = (
        await session.execute(
            select(PartSubtypeProposal.id, PartSubtypeProposal.accepted_at).where(
                PartSubtypeProposal.part_id == part,
                PartSubtypeProposal.status == "accepted",
            )
        )
    ).all()

    # For each shift, the version emitted is the latest body version
    # whose row was created at or before the shift's accept time —
    # i.e. the version the row was at when the shift happened.
    body_sorted = sorted(body_rows, key=lambda r: r.created_at)

    def _version_at(t: datetime) -> str:
        latest = None
        for r in body_sorted:
            if r.created_at <= t:
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
        entries.append(
            (
                r.created_at,
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


@router.get("/{name}/contracts", response_model=PartContractsListResponse)
async def list_part_contracts(
    name: str,
    after: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    session: AsyncSession = Depends(get_session),
) -> PartContractsListResponse:
    limit = validate_limit(limit)

    part = (
        await session.execute(select(Part).where(Part.name == name))
    ).scalar_one_or_none()
    if part is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Part {name!r} not found")

    items, next_cursor = await _list_active_contracts(
        session,
        after=after,
        limit=limit,
        touching_part_id=part.id,
    )
    return PartContractsListResponse(part=part.name, results=items, next=next_cursor)


async def _list_active_contracts(
    session: AsyncSession,
    *,
    after: str | None,
    limit: int,
    touching_part_id=None,
    subtype: str | None = None,
    connection_type: str | None = None,
) -> tuple[list[ContractListItem], str | None]:
    """Paginated listing of contracts with their latest active version.

    `touching_part_id`, if provided, restricts results to contracts where the
    part is owner or counterparty. Otherwise lists every contract.

    `subtype`, if provided, restricts results to contracts of that subtype
    (validated by the caller against CONTRACT_SUBTYPES).

    `connection_type`, if provided, restricts results to that connection
    label (only meaningful when subtype='connection'; the caller validates
    against CONNECTION_TYPES and rejects mismatched subtype/connection_type
    combos).
    """
    latest_active = (
        select(
            ContractVersion.contract_id.label("cv_contract_id"),
            ContractVersion.version_major.label("cv_major"),
            ContractVersion.version_minor.label("cv_minor"),
            ContractVersion.version_patch.label("cv_patch"),
            ContractVersion.created_at.label("cv_created_at"),
            ContractVersion.accepted_at.label("cv_accepted_at"),
        )
        .where(ContractVersion.status == "active")
        .distinct(ContractVersion.contract_id)
        .order_by(
            ContractVersion.contract_id,
            ContractVersion.version_major.desc(),
            ContractVersion.version_minor.desc(),
            ContractVersion.version_patch.desc(),
        )
        .subquery()
    )

    owner_alias = Part.__table__.alias("owner_pt")
    cp_alias = Part.__table__.alias("cp_pt")

    stmt = (
        select(
            Contract.id,
            Contract.subtype,
            Contract.connection_type,
            Contract.created_by_actor,
            owner_alias.c.name.label("owner_name"),
            cp_alias.c.name.label("cp_name"),
            latest_active.c.cv_major,
            latest_active.c.cv_minor,
            latest_active.c.cv_patch,
            latest_active.c.cv_created_at,
            latest_active.c.cv_accepted_at,
        )
        .join(latest_active, Contract.id == latest_active.c.cv_contract_id)
        .join(owner_alias, owner_alias.c.id == Contract.owner_part_id)
        .join(cp_alias, cp_alias.c.id == Contract.counterparty_part_id)
    )

    if touching_part_id is not None:
        stmt = stmt.where(
            or_(
                Contract.owner_part_id == touching_part_id,
                Contract.counterparty_part_id == touching_part_id,
            )
        )

    if subtype is not None:
        stmt = stmt.where(Contract.subtype == subtype)

    if connection_type is not None:
        stmt = stmt.where(Contract.connection_type == connection_type)

    # Pagination order key: COALESCE(accepted_at, created_at) per row, plus id.
    # Use accepted_at if present; otherwise created_at. We compute the value in
    # Python after fetching since SQL coalesce on different sides of the cursor
    # would complicate the tuple comparison. Instead we sort by created_at and
    # use it as the cursor key — close enough; accepted_at is set on accept of
    # an RC which is the same write that created the active row in most cases.
    if after is not None:
        cursor_t, cursor_id = decode_cursor(after)
        stmt = stmt.where(
            tuple_(latest_active.c.cv_created_at, Contract.id)
            < tuple_(cursor_t, cursor_id)
        )

    stmt = stmt.order_by(
        latest_active.c.cv_created_at.desc(), Contract.id.desc()
    ).limit(limit + 1)

    rows = (await session.execute(stmt)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    items: list[ContractListItem] = []
    last_t = None
    last_id = None
    for (
        c_id, c_subtype, c_conn_type, c_creator,
        owner_name, cp_name, vmaj, vmin, vpat, vts, accepted_at,
    ) in rows:
        items.append(
            ContractListItem(
                contract_id=c_id,
                owner=owner_name,
                counterparty=cp_name,
                subtype=c_subtype,
                connection_type=c_conn_type,
                version=str(Version(vmaj, vmin, vpat)),
                updated_at=accepted_at or vts,
                created_by_actor=c_creator,
            )
        )
        last_t, last_id = vts, c_id

    next_cursor = encode_cursor(last_t, last_id) if has_more and last_t else None
    return items, next_cursor


async def _latest_active_contract_version(session: AsyncSession, contract_id) -> ContractVersion | None:
    """Latest (by semver) contract version with status='active'. Active rows are always stable."""
    stmt = (
        select(ContractVersion)
        .where(ContractVersion.contract_id == contract_id, ContractVersion.status == "active")
        .order_by(
            ContractVersion.version_major.desc(),
            ContractVersion.version_minor.desc(),
            ContractVersion.version_patch.desc(),
        )
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


# ---------- Subtype-shift proposals (#33) ----------


async def _part_shift_impact(
    session: AsyncSession,
    *,
    part_id,
    part_name: str,
    new_subtype: str,
    body_markdown: str | None,
) -> SubtypeShiftImpact:
    """Compute the impact preview for a part subtype shift.

    Surfaces every contract whose validation rule would be violated
    by the part's new subtype. Informational only — acceptance does
    not block on related-row impact (the user files separate shifts).
    """
    contracts_touching = (
        await session.execute(
            select(Contract).where(
                or_(
                    Contract.owner_part_id == part_id,
                    Contract.counterparty_part_id == part_id,
                )
            )
        )
    ).scalars().all()

    affected: list[RelatedRowAffected] = []
    for c in contracts_touching:
        is_owner = c.owner_part_id == part_id
        # Replace this part's subtype with `new_subtype` and re-check
        # the contract's per-subtype rule.
        owner_st = new_subtype if is_owner else (
            (await session.get(Part, c.owner_part_id)).subtype
        )
        cp_st = new_subtype if not is_owner else (
            (await session.get(Part, c.counterparty_part_id)).subtype
        )

        violation: str | None = None
        if c.subtype == "binding":
            if owner_st not in BINDING_OWNER_SUBTYPES:
                violation = (
                    f"binding owner must be in {list(BINDING_OWNER_SUBTYPES)}; "
                    f"new owner subtype would be {owner_st!r}"
                )
            elif cp_st != "software":
                violation = (
                    f"binding counterparty must be 'software'; new "
                    f"counterparty subtype would be {cp_st!r}"
                )
        elif c.subtype == "connection" and c.connection_type:
            rule = CONNECTION_RULES[c.connection_type]
            if owner_st not in rule["owner"]:
                violation = (
                    f"connection_type {c.connection_type!r} owner must be in "
                    f"{sorted(rule['owner'])}; new owner subtype would be "
                    f"{owner_st!r}"
                )
            elif cp_st not in rule["counterparty"]:
                violation = (
                    f"connection_type {c.connection_type!r} counterparty must be in "
                    f"{sorted(rule['counterparty'])}; new counterparty subtype "
                    f"would be {cp_st!r}"
                )
        # interaction: no rule, never violated

        if violation:
            owner_part = await session.get(Part, c.owner_part_id)
            cp_part = await session.get(Part, c.counterparty_part_id)
            affected.append(
                RelatedRowAffected(
                    contract_id=c.id,
                    owner=owner_part.name,
                    counterparty=cp_part.name,
                    subtype=c.subtype,
                    reason=violation,
                )
            )

    return SubtypeShiftImpact(
        body_realign_required=body_realign_required(body_markdown, new_subtype),
        # Parts have no own source/target rule — only contracts do.
        source_target_validation="n/a",
        related_rows_potentially_affected=affected,
    )


@router.post(
    "/{name}/subtype-proposals",
    response_model=PartSubtypeShiftCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def propose_part_subtype_shift(
    name: str,
    payload: PartSubtypeShiftCreate,
    x_actor: str | None = Header(default=None, alias="X-Actor"),
    session: AsyncSession = Depends(get_session),
) -> PartSubtypeShiftCreateResponse:
    part = (
        await session.execute(select(Part).where(Part.name == name).with_for_update())
    ).scalar_one_or_none()
    if part is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Part {name!r} not found"
        )

    if payload.new_subtype == part.subtype:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"no-op shift: part {name!r} is already subtype "
                f"{part.subtype!r}; pick a different new_subtype or skip the proposal"
            ),
        )

    latest = await _latest_part_version(session, part.id)
    body_md = latest.markdown if latest else None
    impact = await _part_shift_impact(
        session,
        part_id=part.id,
        part_name=name,
        new_subtype=payload.new_subtype,
        body_markdown=body_md,
    )

    proposal = PartSubtypeProposal(
        part_id=part.id,
        current_subtype_at_propose=part.subtype,
        new_subtype=payload.new_subtype,
        rationale=payload.rationale,
        proposer_actor=x_actor,
        body_realign_required=impact.body_realign_required,
        status="proposal",
    )
    session.add(proposal)
    await session.flush()
    proposal_id = proposal.id
    await session.commit()

    return PartSubtypeShiftCreateResponse(
        proposal_id=proposal_id,
        part_name=name,
        current_subtype=part.subtype,
        new_subtype=payload.new_subtype,
        impact=impact,
        status="proposal",
    )


@router.get(
    "/{name}/subtype-proposals",
    response_model=PartSubtypeShiftListResponse,
)
async def list_part_subtype_shifts(
    name: str,
    session: AsyncSession = Depends(get_session),
) -> PartSubtypeShiftListResponse:
    part = (
        await session.execute(select(Part).where(Part.name == name))
    ).scalar_one_or_none()
    if part is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Part {name!r} not found"
        )

    rows = (
        await session.execute(
            select(PartSubtypeProposal)
            .where(PartSubtypeProposal.part_id == part.id)
            .order_by(PartSubtypeProposal.created_at.desc())
        )
    ).scalars().all()

    entries: list[PartSubtypeShiftEntry] = []
    for r in rows:
        # Impact recomputation is intentionally skipped on list — the
        # body_realign_required flag was snapshotted at propose time
        # and is the only field that survives across reads. Related-
        # rows impact is computed on demand via the propose endpoint
        # if the user wants a fresh view.
        impact = SubtypeShiftImpact(
            body_realign_required=r.body_realign_required,
            source_target_validation="n/a",
            related_rows_potentially_affected=[],
        )
        entries.append(
            PartSubtypeShiftEntry(
                proposal_id=r.id,
                current_subtype=r.current_subtype_at_propose,
                new_subtype=r.new_subtype,
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

    return PartSubtypeShiftListResponse(
        part_name=name,
        current_subtype=part.subtype,
        proposals=entries,
    )


@router.post(
    "/{name}/subtype-proposals/{proposal_id}/accept",
    response_model=PartSubtypeShiftAcceptResponse,
)
async def accept_part_subtype_shift(
    name: str,
    proposal_id: uuid.UUID,
    x_actor: str | None = Header(default=None, alias="X-Actor"),
    single_operator: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
) -> PartSubtypeShiftAcceptResponse:
    part = (
        await session.execute(select(Part).where(Part.name == name).with_for_update())
    ).scalar_one_or_none()
    if part is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Part {name!r} not found"
        )

    proposal = (
        await session.execute(
            select(PartSubtypeProposal).where(
                PartSubtypeProposal.id == proposal_id,
                PartSubtypeProposal.part_id == part.id,
            )
        )
    ).scalar_one_or_none()
    if proposal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subtype-shift proposal {proposal_id} not found for part {name!r}",
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

    # Re-validate at accept time: another proposal may have shifted
    # the part since this one was filed, making this one a no-op.
    if proposal.new_subtype == part.subtype:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"no-op accept: part {name!r} is already subtype "
                f"{part.subtype!r} (a concurrent shift may have landed); "
                f"this proposal is stale"
            ),
        )

    now = datetime.now(timezone.utc)
    shifted_from = part.subtype
    part.subtype = proposal.new_subtype
    part.subtype_shifted_from = shifted_from
    part.subtype_shifted_at = now
    proposal.status = "accepted"
    proposal.accepted_at = now
    proposal.accepted_by = x_actor
    proposal.single_operator_override = single_operator

    await session.commit()

    return PartSubtypeShiftAcceptResponse(
        proposal_id=proposal.id,
        part_name=name,
        shifted_from=shifted_from,
        shifted_to=proposal.new_subtype,
        accepted_at=now,
        accepted_by=x_actor,
        body_realign_required=proposal.body_realign_required,
        single_operator_override=single_operator,
    )
