from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import require_password
from src.db import get_session
from src.models import Contract, ContractVersion, Part, PartVersion
from src.pagination import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    decode_cursor,
    encode_cursor,
    validate_limit,
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
    PartUpdate,
    PartUpdateResponse,
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
    for p_id, p_name, p_subtype, p_repo, p_tracker, p_aliases, vmaj, vmin, vpat, vts in rows:
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
            )
        )
        last_t, last_id = vts, p_id

    next_cursor = encode_cursor(last_t, last_id) if has_more and last_t else None
    return PartListResponse(results=items, next=next_cursor)


@router.post("", response_model=PartCreateResponse, status_code=status.HTTP_201_CREATED)
async def register_part(
    payload: PartCreate,
    session: AsyncSession = Depends(get_session),
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

    stmt = select(
        PartVersion.id,
        PartVersion.version_major,
        PartVersion.version_minor,
        PartVersion.version_patch,
        PartVersion.created_at,
    ).where(PartVersion.part_id == part)

    if after is not None:
        cursor_t, cursor_id = decode_cursor(after)
        stmt = stmt.where(
            tuple_(PartVersion.created_at, PartVersion.id)
            < tuple_(cursor_t, cursor_id)
        )

    stmt = stmt.order_by(
        PartVersion.created_at.desc(), PartVersion.id.desc()
    ).limit(limit + 1)

    rows = (await session.execute(stmt)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    items: list[VersionHistoryItem] = []
    last_t = None
    last_id = None
    for pv_id, vmaj, vmin, vpat, vts in rows:
        items.append(
            VersionHistoryItem(
                version=str(Version(vmaj, vmin, vpat)),
                updated_at=vts,
            )
        )
        last_t, last_id = vts, pv_id

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
) -> tuple[list[ContractListItem], str | None]:
    """Paginated listing of contracts with their latest active version.

    `touching_part_id`, if provided, restricts results to contracts where the
    part is owner or counterparty. Otherwise lists every contract.
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
    for c_id, owner_name, cp_name, vmaj, vmin, vpat, vts, accepted_at in rows:
        items.append(
            ContractListItem(
                contract_id=c_id,
                owner=owner_name,
                counterparty=cp_name,
                version=str(Version(vmaj, vmin, vpat)),
                updated_at=accepted_at or vts,
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
