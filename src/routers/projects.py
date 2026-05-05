"""Projects router (#44).

A project is a tag attached to parts and contracts so the UI and
agents can filter the graph to one project at a time. The graph
itself is unchanged: project membership is metadata that lives on
the part/contract row, not a structural relationship recorded as a
contract.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import require_password
from src.db import get_session
from src.models import Contract, Part, Project
from src.pagination import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    decode_cursor,
    encode_cursor,
    validate_limit,
)
from src.schemas import (
    ProjectCreate,
    ProjectCreateResponse,
    ProjectDetail,
    ProjectListResponse,
    ProjectUpdate,
)

router = APIRouter(
    prefix="/projects", tags=["projects"], dependencies=[Depends(require_password)]
)


async def _project_counts(
    session: AsyncSession, project_id
) -> tuple[int, int]:
    parts = (
        await session.execute(
            select(func.count())
            .select_from(Part)
            .where(
                Part.project_id == project_id,
                Part.deleted_at.is_(None),
            )
        )
    ).scalar_one()
    contracts = (
        await session.execute(
            select(func.count())
            .select_from(Contract)
            .where(
                Contract.project_id == project_id,
                Contract.deleted_at.is_(None),
            )
        )
    ).scalar_one()
    return int(parts), int(contracts)


@router.post(
    "",
    response_model=ProjectCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_project(
    payload: ProjectCreate,
    session: AsyncSession = Depends(get_session),
    x_actor: str | None = Header(default=None, alias="X-Actor"),
) -> ProjectCreateResponse:
    existing = (
        await session.execute(
            select(Project.id).where(Project.name == payload.name)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Project {payload.name!r} already exists",
        )
    proj = Project(
        name=payload.name,
        description=payload.description,
        created_by_actor=x_actor,
    )
    session.add(proj)
    await session.commit()
    await session.refresh(proj)
    return ProjectCreateResponse(
        name=proj.name,
        description=proj.description,
        created_at=proj.created_at,
        created_by_actor=proj.created_by_actor,
    )


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    after: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    session: AsyncSession = Depends(get_session),
) -> ProjectListResponse:
    limit = validate_limit(limit)

    stmt = select(Project)
    if after is not None:
        cursor_t, cursor_id = decode_cursor(after)
        from sqlalchemy import tuple_

        stmt = stmt.where(
            tuple_(Project.created_at, Project.id) < tuple_(cursor_t, cursor_id)
        )
    stmt = stmt.order_by(Project.created_at.desc(), Project.id.desc()).limit(
        limit + 1
    )

    rows = (await session.execute(stmt)).scalars().all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    items: list[ProjectDetail] = []
    last_t = None
    last_id = None
    for proj in rows:
        part_count, contract_count = await _project_counts(session, proj.id)
        items.append(
            ProjectDetail(
                name=proj.name,
                description=proj.description,
                created_at=proj.created_at,
                created_by_actor=proj.created_by_actor,
                part_count=part_count,
                contract_count=contract_count,
            )
        )
        last_t, last_id = proj.created_at, proj.id

    next_cursor = encode_cursor(last_t, last_id) if has_more and last_t else None
    return ProjectListResponse(results=items, next=next_cursor)


@router.get("/{name}", response_model=ProjectDetail)
async def get_project(
    name: str,
    session: AsyncSession = Depends(get_session),
) -> ProjectDetail:
    proj = (
        await session.execute(select(Project).where(Project.name == name))
    ).scalar_one_or_none()
    if proj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {name!r} not found",
        )
    part_count, contract_count = await _project_counts(session, proj.id)
    return ProjectDetail(
        name=proj.name,
        description=proj.description,
        created_at=proj.created_at,
        created_by_actor=proj.created_by_actor,
        part_count=part_count,
        contract_count=contract_count,
    )


@router.put("/{name}", response_model=ProjectDetail)
async def update_project(
    name: str,
    payload: ProjectUpdate,
    session: AsyncSession = Depends(get_session),
) -> ProjectDetail:
    proj = (
        await session.execute(
            select(Project).where(Project.name == name).with_for_update()
        )
    ).scalar_one_or_none()
    if proj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {name!r} not found",
        )
    if "description" in payload.model_fields_set:
        proj.description = payload.description
    await session.commit()
    await session.refresh(proj)
    part_count, contract_count = await _project_counts(session, proj.id)
    return ProjectDetail(
        name=proj.name,
        description=proj.description,
        created_at=proj.created_at,
        created_by_actor=proj.created_by_actor,
        part_count=part_count,
        contract_count=contract_count,
    )
