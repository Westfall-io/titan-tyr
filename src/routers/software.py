from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import require_password
from src.db import get_session
from src.models import Contract, ContractVersion, Software, SoftwareVersion
from src.pagination import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    decode_cursor,
    encode_cursor,
    validate_limit,
)
from src.schemas import (
    ContractListItem,
    SoftwareContractsListResponse,
    SoftwareCreate,
    SoftwareCreateResponse,
    SoftwareDetail,
    SoftwareListItem,
    SoftwareListResponse,
    SoftwareUpdate,
    SoftwareUpdateResponse,
    VersionHistoryItem,
    VersionHistoryResponse,
)
from src.versioning import Version

router = APIRouter(prefix="/software", tags=["software"], dependencies=[Depends(require_password)])


async def _latest_software_version(session: AsyncSession, software_id) -> SoftwareVersion | None:
    stmt = (
        select(SoftwareVersion)
        .where(SoftwareVersion.software_id == software_id)
        .order_by(
            SoftwareVersion.version_major.desc(),
            SoftwareVersion.version_minor.desc(),
            SoftwareVersion.version_patch.desc(),
        )
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


@router.get("", response_model=SoftwareListResponse)
async def list_software(
    after: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    match: str | None = Query(default=None, max_length=128),
    session: AsyncSession = Depends(get_session),
) -> SoftwareListResponse:
    limit = validate_limit(limit)

    latest_versions = (
        select(
            SoftwareVersion.software_id.label("sv_software_id"),
            SoftwareVersion.version_major.label("sv_major"),
            SoftwareVersion.version_minor.label("sv_minor"),
            SoftwareVersion.version_patch.label("sv_patch"),
            SoftwareVersion.created_at.label("sv_created_at"),
        )
        .distinct(SoftwareVersion.software_id)
        .order_by(
            SoftwareVersion.software_id,
            SoftwareVersion.version_major.desc(),
            SoftwareVersion.version_minor.desc(),
            SoftwareVersion.version_patch.desc(),
        )
        .subquery()
    )

    stmt = select(
        Software.id,
        Software.name,
        Software.repo_uri,
        Software.issue_tracker_uri,
        Software.aliases,
        latest_versions.c.sv_major,
        latest_versions.c.sv_minor,
        latest_versions.c.sv_patch,
        latest_versions.c.sv_created_at,
    ).join(latest_versions, Software.id == latest_versions.c.sv_software_id)

    if match is not None:
        # Case-insensitive substring match against name OR any alias. The U+001F
        # separator can't appear inside an alias (control chars are banned at
        # validation), so flattening the array for ILIKE is unambiguous.
        # Escape ILIKE wildcards in user input so "100%" searches literally.
        escaped = match.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        stmt = stmt.where(
            or_(
                Software.name.ilike(pattern, escape="\\"),
                func.array_to_string(Software.aliases, "\x1f").ilike(
                    pattern, escape="\\"
                ),
            )
        )

    if after is not None:
        cursor_t, cursor_id = decode_cursor(after)
        stmt = stmt.where(
            tuple_(latest_versions.c.sv_created_at, Software.id)
            < tuple_(cursor_t, cursor_id)
        )

    stmt = stmt.order_by(
        latest_versions.c.sv_created_at.desc(), Software.id.desc()
    ).limit(limit + 1)

    rows = (await session.execute(stmt)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    items: list[SoftwareListItem] = []
    last_t = None
    last_id = None
    for sw_id, sw_name, sw_repo, sw_tracker, sw_aliases, vmaj, vmin, vpat, vts in rows:
        items.append(
            SoftwareListItem(
                id=sw_id,
                name=sw_name,
                repo_uri=sw_repo,
                issue_tracker_uri=sw_tracker,
                aliases=list(sw_aliases or []),
                version=str(Version(vmaj, vmin, vpat)),
                updated_at=vts,
            )
        )
        last_t, last_id = vts, sw_id

    next_cursor = encode_cursor(last_t, last_id) if has_more and last_t else None
    return SoftwareListResponse(results=items, next=next_cursor)


@router.post("", response_model=SoftwareCreateResponse, status_code=status.HTTP_201_CREATED)
async def register_software(
    payload: SoftwareCreate,
    session: AsyncSession = Depends(get_session),
) -> SoftwareCreateResponse:
    version = Version.parse(payload.version, allow_prerelease=False)
    existing = (
        await session.execute(select(Software.id).where(Software.name == payload.name))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Software {payload.name!r} already exists",
        )
    software = Software(
        name=payload.name,
        repo_uri=payload.repo_uri,
        issue_tracker_uri=payload.issue_tracker_uri,
        aliases=payload.aliases,
    )
    session.add(software)
    await session.flush()
    sv = SoftwareVersion(
        software_id=software.id,
        version_major=version.major,
        version_minor=version.minor,
        version_patch=version.patch,
        markdown=payload.markdown,
    )
    session.add(sv)
    await session.commit()
    return SoftwareCreateResponse(id=software.id, name=software.name, version=str(version))


@router.get("/{name}", response_model=SoftwareDetail)
async def get_software(
    name: str,
    session: AsyncSession = Depends(get_session),
) -> SoftwareDetail:
    software = (
        await session.execute(select(Software).where(Software.name == name))
    ).scalar_one_or_none()
    if software is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Software {name!r} not found")
    latest = await _latest_software_version(session, software.id)
    if latest is None:  # invariant: every software row has at least one version
        raise HTTPException(status_code=500, detail="Software has no versions")
    version = Version(latest.version_major, latest.version_minor, latest.version_patch)
    return SoftwareDetail(
        id=software.id,
        name=software.name,
        repo_uri=software.repo_uri,
        issue_tracker_uri=software.issue_tracker_uri,
        aliases=list(software.aliases or []),
        version=str(version),
        markdown=latest.markdown,
        updated_at=latest.created_at,
    )


@router.put("/{name}", response_model=SoftwareUpdateResponse)
async def update_software(
    name: str,
    payload: SoftwareUpdate,
    session: AsyncSession = Depends(get_session),
) -> SoftwareUpdateResponse:
    software = (
        await session.execute(
            select(Software).where(Software.name == name).with_for_update()
        )
    ).scalar_one_or_none()
    if software is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Software {name!r} not found")

    new_version = Version.parse(payload.version, allow_prerelease=False)
    latest = await _latest_software_version(session, software.id)
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
    # (collapse to []).
    if "repo_uri" in payload.model_fields_set:
        software.repo_uri = payload.repo_uri
    if "issue_tracker_uri" in payload.model_fields_set:
        software.issue_tracker_uri = payload.issue_tracker_uri
    if "aliases" in payload.model_fields_set:
        software.aliases = payload.aliases or []

    sv = SoftwareVersion(
        software_id=software.id,
        version_major=new_version.major,
        version_minor=new_version.minor,
        version_patch=new_version.patch,
        markdown=payload.markdown,
    )
    session.add(sv)
    await session.commit()
    return SoftwareUpdateResponse(name=software.name, version=str(new_version))


@router.get("/{name}/history", response_model=VersionHistoryResponse)
async def get_software_history(
    name: str,
    after: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    session: AsyncSession = Depends(get_session),
) -> VersionHistoryResponse:
    limit = validate_limit(limit)

    software = (
        await session.execute(select(Software.id).where(Software.name == name))
    ).scalar_one_or_none()
    if software is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Software {name!r} not found")

    stmt = select(
        SoftwareVersion.id,
        SoftwareVersion.version_major,
        SoftwareVersion.version_minor,
        SoftwareVersion.version_patch,
        SoftwareVersion.created_at,
    ).where(SoftwareVersion.software_id == software)

    if after is not None:
        cursor_t, cursor_id = decode_cursor(after)
        stmt = stmt.where(
            tuple_(SoftwareVersion.created_at, SoftwareVersion.id)
            < tuple_(cursor_t, cursor_id)
        )

    stmt = stmt.order_by(
        SoftwareVersion.created_at.desc(), SoftwareVersion.id.desc()
    ).limit(limit + 1)

    rows = (await session.execute(stmt)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    items: list[VersionHistoryItem] = []
    last_t = None
    last_id = None
    for sv_id, vmaj, vmin, vpat, vts in rows:
        items.append(
            VersionHistoryItem(
                version=str(Version(vmaj, vmin, vpat)),
                updated_at=vts,
            )
        )
        last_t, last_id = vts, sv_id

    next_cursor = encode_cursor(last_t, last_id) if has_more and last_t else None
    return VersionHistoryResponse(results=items, next=next_cursor)


@router.get("/{name}/contracts", response_model=SoftwareContractsListResponse)
async def list_software_contracts(
    name: str,
    after: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    session: AsyncSession = Depends(get_session),
) -> SoftwareContractsListResponse:
    limit = validate_limit(limit)

    software = (
        await session.execute(select(Software).where(Software.name == name))
    ).scalar_one_or_none()
    if software is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Software {name!r} not found")

    items, next_cursor = await _list_active_contracts(
        session,
        after=after,
        limit=limit,
        touching_software_id=software.id,
    )
    return SoftwareContractsListResponse(software=software.name, results=items, next=next_cursor)


async def _list_active_contracts(
    session: AsyncSession,
    *,
    after: str | None,
    limit: int,
    touching_software_id=None,
) -> tuple[list[ContractListItem], str | None]:
    """Paginated listing of contracts with their latest active version.

    `touching_software_id`, if provided, restricts results to contracts where the
    software is owner or counterparty. Otherwise lists every contract.
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

    owner_alias = Software.__table__.alias("owner_sw")
    cp_alias = Software.__table__.alias("cp_sw")

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
        .join(owner_alias, owner_alias.c.id == Contract.owner_software_id)
        .join(cp_alias, cp_alias.c.id == Contract.counterparty_software_id)
    )

    if touching_software_id is not None:
        stmt = stmt.where(
            or_(
                Contract.owner_software_id == touching_software_id,
                Contract.counterparty_software_id == touching_software_id,
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
