from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import current_actor, require_scope, require_token
from src.db import get_session
from src.models import (
    Contract,
    ContractVersion,
    Part,
    PartDeletionProposal,
    PartNameProposal,
    PartSubtypeProposal,
    PartVersion,
    Project,
)
from src.pagination import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    decode_cursor,
    encode_cursor,
    validate_limit,
)
from src.routers._projects import resolve_project_slug
from src.routers._rules import BINDING_OWNER_SUBTYPES, CONNECTION_RULES
from src.routers._subtype_helpers import (
    body_realign_required,
    enforce_human_confirmation,
    enforce_two_party,
    get_active_agent_actors,
)
from src.schemas import (
    PART_SUBTYPES,
    PROJECT_NONE_SENTINEL,
    ContractListItem,
    PartContractsListResponse,
    PartCreate,
    PartCreateResponse,
    PartDeletionAcceptResponse,
    PartDeletionImpact,
    PartDeletionProposalCreate,
    PartDeletionProposalCreateResponse,
    PartDeletionProposalEntry,
    PartDeletionProposalListResponse,
    PartDetail,
    PartListItem,
    PartListResponse,
    PartNameShiftAcceptResponse,
    PartNameShiftCreate,
    PartNameShiftCreateResponse,
    PartNameShiftEntry,
    PartNameShiftListResponse,
    PartSubtypeShiftAcceptResponse,
    PartSubtypeShiftCreate,
    PartSubtypeShiftCreateResponse,
    PartSubtypeShiftEntry,
    PartSubtypeShiftListResponse,
    PartUpdate,
    PartUpdateResponse,
    RelatedRowAffected,
    SubtypeShiftImpact,
    TouchingContractRef,
    VersionHistoryItem,
    VersionHistoryResponse,
)
from src.versioning import Version

router = APIRouter(prefix="/parts", tags=["parts"], dependencies=[Depends(require_token)])


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


@router.get(
    "",
    response_model=PartListResponse,
    dependencies=[Depends(require_scope("read"))],
)
async def list_parts(
    after: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    match: str | None = Query(default=None, max_length=128),
    subtype: str | None = Query(default=None),
    project: str | None = Query(default=None, max_length=64),
    include_deleted: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
) -> PartListResponse:
    limit = validate_limit(limit)

    if subtype is not None and subtype not in PART_SUBTYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"subtype must be one of {sorted(PART_SUBTYPES)}",
        )

    # Project filter (#44). Three modes:
    #   - omitted / empty           → no filter, default behaviour
    #   - PROJECT_NONE_SENTINEL     → only unprojected rows (project_id IS NULL)
    #   - any other slug            → resolve to project_id, filter; 422 if unknown
    project_filter_id = None
    project_filter_unprojected = False
    if project is not None and project != "":
        if project == PROJECT_NONE_SENTINEL:
            project_filter_unprojected = True
        else:
            project_filter_id = await resolve_project_slug(session, project)

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

    stmt = (
        select(
            Part.id,
            Part.name,
            Part.subtype,
            Part.repo_uri,
            Part.issue_tracker_uri,
            Part.aliases,
            Part.created_by_actor,
            Part.deleted_at,
            Project.name.label("project_name"),
            latest_versions.c.pv_major,
            latest_versions.c.pv_minor,
            latest_versions.c.pv_patch,
            latest_versions.c.pv_created_at,
        )
        .join(latest_versions, Part.id == latest_versions.c.pv_part_id)
        .outerjoin(Project, Part.project_id == Project.id)
    )

    if subtype is not None:
        stmt = stmt.where(Part.subtype == subtype)

    if not include_deleted:
        stmt = stmt.where(Part.deleted_at.is_(None))

    if project_filter_unprojected:
        stmt = stmt.where(Part.project_id.is_(None))
    elif project_filter_id is not None:
        stmt = stmt.where(Part.project_id == project_filter_id)

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
        p_deleted_at, p_project, vmaj, vmin, vpat, vts,
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
                project=p_project,
                deleted_at=p_deleted_at,
            )
        )
        last_t, last_id = vts, p_id

    next_cursor = encode_cursor(last_t, last_id) if has_more and last_t else None
    return PartListResponse(results=items, next=next_cursor)


@router.post(
    "",
    response_model=PartCreateResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_scope("write"))],
)
async def register_part(
    payload: PartCreate,
    session: AsyncSession = Depends(get_session),
    x_actor: str | None = Depends(current_actor),
) -> PartCreateResponse:
    version = Version.parse(payload.version, allow_prerelease=False)
    # The uniqueness key on `parts.name` is partial-on-live (#76),
    # so soft-deleted rows do not block re-registration. Match the
    # router-level existence check to that semantics.
    existing = (
        await session.execute(
            select(Part.id).where(
                Part.name == payload.name, Part.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Part {payload.name!r} already exists",
        )
    project_id = await resolve_project_slug(session, payload.project)
    part = Part(
        name=payload.name,
        subtype=payload.subtype,
        repo_uri=payload.repo_uri,
        issue_tracker_uri=payload.issue_tracker_uri,
        aliases=payload.aliases,
        created_by_actor=x_actor,
        project_id=project_id,
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
    await session.refresh(pv)
    project_name = None
    if part.project_id is not None:
        proj = await session.get(Project, part.project_id)
        project_name = proj.name if proj is not None else None
    return PartCreateResponse(
        id=part.id,
        name=part.name,
        subtype=part.subtype,
        repo_uri=part.repo_uri,
        issue_tracker_uri=part.issue_tracker_uri,
        aliases=list(part.aliases or []),
        version=str(version),
        markdown=pv.markdown,
        updated_at=pv.created_at,
        created_by_actor=part.created_by_actor,
        project=project_name,
    )


@router.get(
    "/{name}",
    response_model=PartDetail,
    dependencies=[Depends(require_scope("read"))],
)
async def get_part(
    name: str,
    include_deleted: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
) -> PartDetail:
    row = (
        await session.execute(
            select(Part, Project.name.label("project_name"))
            .outerjoin(Project, Part.project_id == Project.id)
            .where(Part.name == name)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Part {name!r} not found")
    part, project_name = row
    if part.deleted_at is not None and not include_deleted:
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
        project=project_name,
        deleted_at=part.deleted_at,
        deleted_by_proposer_actor=part.deleted_by_proposer_actor,
        deleted_by_acceptor_actor=part.deleted_by_acceptor_actor,
        deletion_rationale=part.deletion_rationale,
    )


@router.put(
    "/{name}",
    response_model=PartUpdateResponse,
    dependencies=[Depends(require_scope("write"))],
)
async def update_part(
    name: str,
    payload: PartUpdate,
    session: AsyncSession = Depends(get_session),
    x_actor: str | None = Depends(current_actor),
) -> PartUpdateResponse:
    part = (
        await session.execute(
            select(Part).where(Part.name == name).with_for_update()
        )
    ).scalar_one_or_none()
    if part is None or part.deleted_at is not None:
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
    # Project tag (#44). Explicit null clears (move to unprojected); a
    # slug resolves to the project's id (422 if unknown). Field absent
    # = unchanged.
    if "project" in payload.model_fields_set:
        part.project_id = await resolve_project_slug(session, payload.project)

    # First-write-wins backfill of created_by_actor (#54). Honor X-Actor
    # only when the current value is NULL — this lets the original
    # registrant claim a legacy row (registered before X-Actor existed,
    # or before they had it set) without permitting subsequent PUTs to
    # silently overwrite an already-attributed row's identity.
    if x_actor is not None and part.created_by_actor is None:
        part.created_by_actor = x_actor

    pv = PartVersion(
        part_id=part.id,
        version_major=new_version.major,
        version_minor=new_version.minor,
        version_patch=new_version.patch,
        markdown=payload.markdown,
    )
    session.add(pv)
    await session.commit()
    await session.refresh(pv)
    project_name = None
    if part.project_id is not None:
        proj = await session.get(Project, part.project_id)
        project_name = proj.name if proj is not None else None
    return PartUpdateResponse(
        id=part.id,
        name=part.name,
        subtype=part.subtype,
        repo_uri=part.repo_uri,
        issue_tracker_uri=part.issue_tracker_uri,
        aliases=list(part.aliases or []),
        version=str(new_version),
        markdown=pv.markdown,
        updated_at=pv.created_at,
        created_by_actor=part.created_by_actor,
        project=project_name,
    )


@router.get(
    "/{name}/history",
    response_model=VersionHistoryResponse,
    dependencies=[Depends(require_scope("read"))],
)
async def get_part_history(
    name: str,
    after: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    include_deleted: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
) -> VersionHistoryResponse:
    limit = validate_limit(limit)

    part_row = (
        await session.execute(
            select(Part.id, Part.deleted_at).where(Part.name == name)
        )
    ).first()
    if part_row is None or (
        part_row.deleted_at is not None and not include_deleted
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Part {name!r} not found")
    part = part_row.id

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
            select(
                PartSubtypeProposal.id,
                PartSubtypeProposal.accepted_at,
                PartSubtypeProposal.proposer_actor,
                PartSubtypeProposal.accepted_by,
                PartSubtypeProposal.single_operator_override,
            ).where(
                PartSubtypeProposal.part_id == part,
                PartSubtypeProposal.status == "accepted",
            )
        )
    ).all()

    name_shift_rows = (
        await session.execute(
            select(
                PartNameProposal.id,
                PartNameProposal.accepted_at,
                PartNameProposal.proposer_actor,
                PartNameProposal.accepted_by,
                PartNameProposal.single_operator_override,
            ).where(
                PartNameProposal.part_id == part,
                PartNameProposal.status == "accepted",
            )
        )
    ).all()

    # Deletion proposals contribute two events per row:
    # `deletion_proposed` at created_at and `deletion_accepted` at
    # accepted_at (if accepted). Both are gated behind
    # `include_deleted=true` since deletion is the kind of audit
    # event that warrants the explicit opt-in (#76).
    deletion_rows = []
    if include_deleted:
        deletion_rows = (
            await session.execute(
                select(
                    PartDeletionProposal.id,
                    PartDeletionProposal.created_at,
                    PartDeletionProposal.accepted_at,
                    PartDeletionProposal.proposer_actor,
                    PartDeletionProposal.accepted_by,
                    PartDeletionProposal.single_operator_override,
                    PartDeletionProposal.status,
                ).where(PartDeletionProposal.part_id == part)
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

    # Tuple shape: (timestamp, row_id, kind, version_str, proposer,
    # acceptor, single_operator_override). The latter three surface
    # per-version actor on history (#51). For body_bump entries the
    # actor fields are always None — PartVersion does not yet carry
    # propose-accept attribution (parts have direct-write versioning;
    # the issue defers populating these as forward-applies once parts
    # gain a content-proposal lifecycle).
    entries: list[
        tuple[datetime, uuid.UUID, str, str, str | None, str | None, bool]
    ] = []
    for r in body_rows:
        entries.append(
            (
                r.created_at,
                r.id,
                "body_bump",
                str(Version(r.version_major, r.version_minor, r.version_patch)),
                None,
                None,
                False,
            )
        )
    for r in shift_rows:
        if r.accepted_at is None:
            continue
        entries.append(
            (
                r.accepted_at,
                r.id,
                "subtype_shift",
                _version_at(r.accepted_at),
                r.proposer_actor,
                r.accepted_by,
                bool(r.single_operator_override),
            )
        )
    for r in name_shift_rows:
        if r.accepted_at is None:
            continue
        entries.append(
            (
                r.accepted_at,
                r.id,
                "name_shift",
                _version_at(r.accepted_at),
                r.proposer_actor,
                r.accepted_by,
                bool(r.single_operator_override),
            )
        )
    for r in deletion_rows:
        # The propose event records the proposer; acceptor is null
        # until accept lands. Both events carry the proposer for
        # continuity (mirrors #69's contract treatment).
        entries.append(
            (
                r.created_at,
                r.id,
                "deletion_proposed",
                _version_at(r.created_at),
                r.proposer_actor,
                None,
                False,
            )
        )
        if r.accepted_at is not None:
            entries.append(
                (
                    r.accepted_at,
                    r.id,
                    "deletion_accepted",
                    _version_at(r.accepted_at),
                    r.proposer_actor,
                    r.accepted_by,
                    bool(r.single_operator_override),
                )
            )

    entries.sort(key=lambda e: (e[0], e[1]), reverse=True)

    if after is not None:
        cursor_t, cursor_id = decode_cursor(after)
        entries = [e for e in entries if (e[0], e[1]) < (cursor_t, cursor_id)]

    has_more = len(entries) > limit
    entries = entries[:limit]

    items = [
        VersionHistoryItem(
            version=v,
            updated_at=ts,
            kind=k,
            proposer_actor=proposer,
            acceptor_actor=acceptor,
            single_operator_override=override,
        )
        for ts, _, k, v, proposer, acceptor, override in entries
    ]
    last_t, last_id = (entries[-1][0], entries[-1][1]) if entries else (None, None)
    next_cursor = encode_cursor(last_t, last_id) if has_more and last_t else None
    return VersionHistoryResponse(results=items, next=next_cursor)


@router.get(
    "/{name}/contracts",
    response_model=PartContractsListResponse,
    dependencies=[Depends(require_scope("read"))],
)
async def list_part_contracts(
    name: str,
    after: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    include_deleted: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
) -> PartContractsListResponse:
    limit = validate_limit(limit)

    part = (
        await session.execute(select(Part).where(Part.name == name))
    ).scalar_one_or_none()
    # The same `?include_deleted=true` flag controls visibility of
    # both the part itself and the contracts it touches (#76, #69).
    # A soft-deleted part is hidden from this listing by default.
    if part is None or (part.deleted_at is not None and not include_deleted):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Part {name!r} not found")

    items, next_cursor = await _list_active_contracts(
        session,
        after=after,
        limit=limit,
        touching_part_id=part.id,
        include_deleted=include_deleted,
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
    project_filter_id=None,
    project_filter_unprojected: bool = False,
    include_deleted: bool = False,
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

    `project_filter_id` / `project_filter_unprojected` (#44) restrict to
    contracts in a specific project or to unprojected contracts. The
    caller resolves the project slug to an id (or sets the unprojected
    flag) before calling.
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
            Contract.deleted_at,
            owner_alias.c.name.label("owner_name"),
            cp_alias.c.name.label("cp_name"),
            Project.name.label("project_name"),
            latest_active.c.cv_major,
            latest_active.c.cv_minor,
            latest_active.c.cv_patch,
            latest_active.c.cv_created_at,
            latest_active.c.cv_accepted_at,
        )
        .join(latest_active, Contract.id == latest_active.c.cv_contract_id)
        .join(owner_alias, owner_alias.c.id == Contract.owner_part_id)
        .join(cp_alias, cp_alias.c.id == Contract.counterparty_part_id)
        .outerjoin(Project, Contract.project_id == Project.id)
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

    if not include_deleted:
        stmt = stmt.where(Contract.deleted_at.is_(None))

    if project_filter_unprojected:
        stmt = stmt.where(Contract.project_id.is_(None))
    elif project_filter_id is not None:
        stmt = stmt.where(Contract.project_id == project_filter_id)

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
        c_id, c_subtype, c_conn_type, c_creator, c_deleted_at,
        owner_name, cp_name, project_name,
        vmaj, vmin, vpat, vts, accepted_at,
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
                project=project_name,
                deleted_at=c_deleted_at,
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
    dependencies=[Depends(require_scope("write"))],
)
async def propose_part_subtype_shift(
    name: str,
    payload: PartSubtypeShiftCreate,
    x_actor: str | None = Depends(current_actor),
    session: AsyncSession = Depends(get_session),
) -> PartSubtypeShiftCreateResponse:
    part = (
        await session.execute(select(Part).where(Part.name == name).with_for_update())
    ).scalar_one_or_none()
    if part is None or part.deleted_at is not None:
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
    dependencies=[Depends(require_scope("read"))],
)
async def list_part_subtype_shifts(
    name: str,
    session: AsyncSession = Depends(get_session),
) -> PartSubtypeShiftListResponse:
    part = (
        await session.execute(select(Part).where(Part.name == name))
    ).scalar_one_or_none()
    if part is None or part.deleted_at is not None:
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
    dependencies=[Depends(require_scope("write"))],
)
async def accept_part_subtype_shift(
    name: str,
    proposal_id: uuid.UUID,
    x_actor: str | None = Depends(current_actor),
    single_operator: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
) -> PartSubtypeShiftAcceptResponse:
    part = (
        await session.execute(select(Part).where(Part.name == name).with_for_update())
    ).scalar_one_or_none()
    if part is None or part.deleted_at is not None:
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


# ---------- Name-shift proposals (#45) ----------
#
# Renaming a part is a single UPDATE on parts.name. Contracts hold
# owner_part_id / counterparty_part_id by id (not name), so existing
# contracts surface the new name automatically on the next GET via
# the join — no contract-side cascade. The legibility risk is
# entirely consumer-side (a deployed UI build holding the old slug
# will 404 against /parts/{old}); that's tracked separately as a
# render-only obligation on the mimiron contract bump.


@router.post(
    "/{name}/name-proposals",
    response_model=PartNameShiftCreateResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_scope("write"))],
)
async def propose_part_name_shift(
    name: str,
    payload: PartNameShiftCreate,
    x_actor: str | None = Depends(current_actor),
    session: AsyncSession = Depends(get_session),
) -> PartNameShiftCreateResponse:
    part = (
        await session.execute(
            select(Part).where(Part.name == name).with_for_update()
        )
    ).scalar_one_or_none()
    if part is None or part.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Part {name!r} not found"
        )

    if payload.new_name == part.name:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"no-op shift: part is already named {part.name!r}; "
                f"pick a different new_name or skip the proposal"
            ),
        )

    # Reject early if another live part already owns the proposed
    # slug. Soft-deleted rows do not block per #76's partial-on-live
    # uniqueness key. Re-checked at accept time (the check is racy —
    # another shift might land between propose and accept).
    clash = (
        await session.execute(
            select(Part.id).where(
                Part.name == payload.new_name, Part.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if clash is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Part {payload.new_name!r} already exists",
        )

    proposal = PartNameProposal(
        part_id=part.id,
        current_name_at_propose=part.name,
        new_name=payload.new_name,
        rationale=payload.rationale,
        proposer_actor=x_actor,
        status="proposal",
    )
    session.add(proposal)
    await session.flush()
    proposal_id = proposal.id
    await session.commit()

    return PartNameShiftCreateResponse(
        proposal_id=proposal_id,
        part_name=name,
        current_name=part.name,
        new_name=payload.new_name,
        rationale=payload.rationale,
        proposer_actor=x_actor,
    )


@router.get(
    "/{name}/name-proposals",
    response_model=PartNameShiftListResponse,
    dependencies=[Depends(require_scope("read"))],
)
async def list_part_name_shifts(
    name: str,
    session: AsyncSession = Depends(get_session),
) -> PartNameShiftListResponse:
    part = (
        await session.execute(select(Part).where(Part.name == name))
    ).scalar_one_or_none()
    if part is None or part.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Part {name!r} not found"
        )

    rows = (
        await session.execute(
            select(PartNameProposal)
            .where(PartNameProposal.part_id == part.id)
            .order_by(PartNameProposal.created_at.desc())
        )
    ).scalars().all()

    entries = [
        PartNameShiftEntry(
            proposal_id=r.id,
            current_name_at_propose=r.current_name_at_propose,
            new_name=r.new_name,
            rationale=r.rationale,
            proposer_actor=r.proposer_actor,
            status=r.status,
            created_at=r.created_at,
            accepted_at=r.accepted_at,
            accepted_by=r.accepted_by,
            single_operator_override=r.single_operator_override,
        )
        for r in rows
    ]

    return PartNameShiftListResponse(
        part_name=part.name,
        current_name=part.name,
        proposals=entries,
    )


@router.post(
    "/{name}/name-proposals/{proposal_id}/accept",
    response_model=PartNameShiftAcceptResponse,
    dependencies=[Depends(require_scope("write"))],
)
async def accept_part_name_shift(
    name: str,
    proposal_id: uuid.UUID,
    x_actor: str | None = Depends(current_actor),
    single_operator: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
) -> PartNameShiftAcceptResponse:
    part = (
        await session.execute(
            select(Part).where(Part.name == name).with_for_update()
        )
    ).scalar_one_or_none()
    if part is None or part.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Part {name!r} not found"
        )

    proposal = (
        await session.execute(
            select(PartNameProposal).where(
                PartNameProposal.id == proposal_id,
                PartNameProposal.part_id == part.id,
            )
        )
    ).scalar_one_or_none()
    if proposal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Name-shift proposal {proposal_id} not found for part {name!r}",
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

    # Re-validate at accept time. Two failure modes:
    # 1. No-op: another name-shift may have already renamed the part
    #    to the proposed slug.
    # 2. Slug clash: another part may have taken the proposed slug
    #    (either via its own registration or its own name-shift)
    #    since this proposal was filed.
    if proposal.new_name == part.name:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"no-op accept: part is already named {part.name!r} "
                f"(a concurrent shift may have landed); this proposal is stale"
            ),
        )

    clash = (
        await session.execute(
            select(Part.id).where(
                Part.name == proposal.new_name,
                Part.id != part.id,
                # Match the partial-on-live uniqueness key (#76):
                # soft-deleted rows do not block a name shift.
                Part.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if clash is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"slug {proposal.new_name!r} is now taken by another part; "
                f"this proposal can no longer apply. File a fresh proposal "
                f"with a different new_name."
            ),
        )

    now = datetime.now(timezone.utc)
    shifted_from = part.name
    part.name = proposal.new_name
    part.name_shifted_from = shifted_from
    part.name_shifted_at = now
    proposal.status = "accepted"
    proposal.accepted_at = now
    proposal.accepted_by = x_actor
    proposal.single_operator_override = single_operator

    await session.commit()

    return PartNameShiftAcceptResponse(
        proposal_id=proposal.id,
        part_id=part.id,
        shifted_from_name=shifted_from,
        shifted_to_name=proposal.new_name,
        accepted_at=now,
        accepted_by=x_actor,
        single_operator_override=single_operator,
    )


# ---------- Deletion proposals (#76) ----------
#
# Parts-side parallel of #69's contract deletion. Acceptance soft-
# deletes by stamping `parts.deleted_at` plus the proposer / acceptor
# / rationale columns. Two extras vs the contract flow:
#
#   1. Cascade-vs-block. A part is a node, contracts are edges. Live
#      touching contracts hard-block the accept (422) unless
#      `?cascade=true`, which soft-deletes each touching contract in
#      the same transaction. Contracts get the same proposer /
#      acceptor and a rationale prefixed
#      "cascaded from /propose-part-deletion: ...".
#
#   2. Human confirmation. The acceptor X-Actor must NOT be in the
#      live agent_actors allowlist (DB-backed since #78; previously
#      a config default in #76); ?single_operator=true is forbidden.
#      Two agents bouncing the handshake otherwise satisfies the soft
#      two-party rule without a human ever confirming a cascading
#      wipe.


async def _compute_part_deletion_impact(
    session: AsyncSession,
    *,
    part: Part,
) -> tuple[PartDeletionImpact, list[Contract]]:
    """Build the impact block + return the touching live contracts.

    Returns the populated `PartDeletionImpact` plus the list of
    live Contract rows that touch this part (owner or counterparty
    side). Returning the list separately lets the cascade path
    operate on the same set without re-querying.
    """
    # Touching contracts (live only — soft-deleted contracts don't
    # need cascading, they're already gone).
    contracts = (
        await session.execute(
            select(Contract)
            .where(
                or_(
                    Contract.owner_part_id == part.id,
                    Contract.counterparty_part_id == part.id,
                ),
                Contract.deleted_at.is_(None),
            )
        )
    ).scalars().all()

    refs: list[TouchingContractRef] = []
    for c in contracts:
        owner = await session.get(Part, c.owner_part_id)
        cp = await session.get(Part, c.counterparty_part_id)
        refs.append(
            TouchingContractRef(
                contract_id=c.id,
                owner=owner.name,
                counterparty=cp.name,
                subtype=c.subtype,
                connection_type=c.connection_type,
            )
        )

    # Body references: scan the latest active version of every other
    # live part for a whole-token match of THIS part's name. Same
    # treatment as #69's contract impact block; the bound prevents
    # false positives on shared substrings.
    pattern = (
        r"(?<![a-z0-9-])" + re.escape(part.name) + r"(?![a-z0-9-])"
    )
    referenced: list[str] = []
    other_part_rows = (
        await session.execute(
            select(Part).where(
                Part.id != part.id, Part.deleted_at.is_(None)
            )
        )
    ).scalars().all()
    for other in other_part_rows:
        latest = await _latest_part_version(session, other.id)
        if latest is None or latest.markdown is None:
            continue
        if re.search(pattern, latest.markdown):
            referenced.append(other.name)

    # Active history events on the part.
    body_count = (
        await session.execute(
            select(func.count())
            .select_from(PartVersion)
            .where(PartVersion.part_id == part.id)
        )
    ).scalar_one()
    accepted_subtype = (
        await session.execute(
            select(func.count())
            .select_from(PartSubtypeProposal)
            .where(
                PartSubtypeProposal.part_id == part.id,
                PartSubtypeProposal.status == "accepted",
            )
        )
    ).scalar_one()
    accepted_name = (
        await session.execute(
            select(func.count())
            .select_from(PartNameProposal)
            .where(
                PartNameProposal.part_id == part.id,
                PartNameProposal.status == "accepted",
            )
        )
    ).scalar_one()

    impact = PartDeletionImpact(
        touching_contracts=refs,
        referenced_in_part_bodies=referenced,
        active_history_entries=int(body_count)
        + int(accepted_subtype)
        + int(accepted_name),
    )
    return impact, list(contracts)


@router.post(
    "/{name}/deletion-proposals",
    response_model=PartDeletionProposalCreateResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_scope("write"))],
)
async def propose_part_deletion(
    name: str,
    payload: PartDeletionProposalCreate,
    x_actor: str | None = Depends(current_actor),
    session: AsyncSession = Depends(get_session),
) -> PartDeletionProposalCreateResponse:
    part = (
        await session.execute(
            select(Part).where(Part.name == name).with_for_update()
        )
    ).scalar_one_or_none()
    if part is None or part.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Part {name!r} not found"
        )

    impact, _ = await _compute_part_deletion_impact(session, part=part)

    proposal = PartDeletionProposal(
        part_id=part.id,
        rationale=payload.rationale,
        proposer_actor=x_actor,
        status="proposal",
    )
    session.add(proposal)
    await session.flush()
    proposal_id = proposal.id
    await session.commit()

    return PartDeletionProposalCreateResponse(
        proposal_id=proposal_id,
        part_name=part.name,
        rationale=payload.rationale,
        proposer_actor=x_actor,
        impact=impact,
        status="proposal",
    )


@router.get(
    "/{name}/deletion-proposals",
    response_model=PartDeletionProposalListResponse,
    dependencies=[Depends(require_scope("read"))],
)
async def list_part_deletion_proposals(
    name: str,
    include_deleted: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
) -> PartDeletionProposalListResponse:
    part = (
        await session.execute(select(Part).where(Part.name == name))
    ).scalar_one_or_none()
    if part is None or (
        part.deleted_at is not None and not include_deleted
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Part {name!r} not found"
        )

    rows = (
        await session.execute(
            select(PartDeletionProposal)
            .where(PartDeletionProposal.part_id == part.id)
            .order_by(PartDeletionProposal.created_at.desc())
        )
    ).scalars().all()

    entries = [
        PartDeletionProposalEntry(
            proposal_id=r.id,
            rationale=r.rationale,
            proposer_actor=r.proposer_actor,
            status=r.status,
            created_at=r.created_at,
            accepted_at=r.accepted_at,
            accepted_by=r.accepted_by,
            single_operator_override=r.single_operator_override,
            cascade=r.cascade,
        )
        for r in rows
    ]
    return PartDeletionProposalListResponse(
        part_name=part.name, proposals=entries
    )


@router.post(
    "/{name}/deletion-proposals/{proposal_id}/accept",
    response_model=PartDeletionAcceptResponse,
    dependencies=[Depends(require_scope("write"))],
)
async def accept_part_deletion(
    name: str,
    proposal_id: uuid.UUID,
    x_actor: str | None = Depends(current_actor),
    single_operator: bool = Query(default=False),
    cascade: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
) -> PartDeletionAcceptResponse:
    # Human-confirmation rule (#76): part deletion is destructive +
    # cascading; the soft two-party rule (proposer != acceptor) isn't
    # enough on its own. The bypass that suspends two-party
    # (single_operator=true) defeats the human-confirmation
    # purpose, so reject it up-front before doing any DB work.
    if single_operator:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "?single_operator=true is not allowed for part deletion; "
                "the human-confirmation rule requires a real two-party "
                "handshake with a human acceptor"
            ),
        )

    part = (
        await session.execute(
            select(Part).where(Part.name == name).with_for_update()
        )
    ).scalar_one_or_none()
    if part is None or part.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Part {name!r} not found"
        )

    proposal = (
        await session.execute(
            select(PartDeletionProposal).where(
                PartDeletionProposal.id == proposal_id,
                PartDeletionProposal.part_id == part.id,
            )
        )
    ).scalar_one_or_none()
    if proposal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Deletion proposal {proposal_id} not found for "
                f"part {part.name!r}"
            ),
        )
    if proposal.status != "proposal":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"proposal {proposal_id} is in status {proposal.status!r}; "
                f"only 'proposal' rows can be accepted"
            ),
        )

    # Soft two-party (distinct actors) AND strict
    # human-confirmation (acceptor not in agent allowlist). Together
    # they ensure no two-agent round-trip can wipe a part + cascade
    # to its contracts.
    enforce_two_party(
        proposer_actor=proposal.proposer_actor,
        acceptor_actor=x_actor,
        single_operator=False,
    )
    enforce_human_confirmation(
        acceptor_actor=x_actor,
        known_agents=await get_active_agent_actors(session),
    )

    # Re-compute impact at accept time so the response reflects
    # current state. Touching-contract list drives the cascade-vs-
    # block decision: non-empty + cascade=false → 422 hard-block.
    impact, touching = await _compute_part_deletion_impact(session, part=part)
    if touching and not cascade:
        contract_ids = [str(c.id) for c in touching]
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"part {part.name!r} has {len(touching)} live touching "
                f"contract(s): {contract_ids}. Either delete them first "
                f"via /propose-contract-deletion + /accept-contract-deletion, "
                f"or pass ?cascade=true to soft-delete them in the same "
                f"transaction."
            ),
        )

    now = datetime.now(timezone.utc)
    cascaded_ids: list[uuid.UUID] = []
    if cascade:
        # Stamp each touching contract directly. We don't create a
        # contract_deletion_proposal row per cascade — the audit
        # trail is "find the part deleted at the same instant for
        # context" via matching timestamps + actors. The rationale
        # prefix makes the cause explicit when a reader looks at
        # the contract row directly.
        cascade_rationale = (
            f"cascaded from /propose-part-deletion on {part.name!r}: "
            f"{proposal.rationale}"
        )
        for c in touching:
            c.deleted_at = now
            c.deleted_by_proposer_actor = proposal.proposer_actor
            c.deleted_by_acceptor_actor = x_actor
            c.deletion_rationale = cascade_rationale
            c.deletion_single_operator_override = False
            cascaded_ids.append(c.id)

    part.deleted_at = now
    part.deleted_by_proposer_actor = proposal.proposer_actor
    part.deleted_by_acceptor_actor = x_actor
    part.deletion_rationale = proposal.rationale
    # Always false on part deletion — the route rejects
    # ?single_operator=true above. Stamped explicitly for clarity.
    part.deletion_single_operator_override = False
    proposal.status = "accepted"
    proposal.accepted_at = now
    proposal.accepted_by = x_actor
    proposal.single_operator_override = False
    proposal.cascade = cascade

    await session.commit()

    return PartDeletionAcceptResponse(
        proposal_id=proposal.id,
        part_name=part.name,
        deleted_at=now,
        proposer_actor=proposal.proposer_actor,
        acceptor_actor=x_actor,
        rationale=proposal.rationale,
        impact=impact,
        cascade=cascade,
        cascaded_contract_ids=cascaded_ids,
    )
