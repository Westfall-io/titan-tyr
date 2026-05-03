from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import require_password
from src.db import get_session
from src.models import Template, TemplateVersion
from src.schemas import (
    TemplateProposalAcceptResponse,
    TemplateProposalCreate,
    TemplateProposalCreateResponse,
    TemplateProposalEntry,
    TemplateProposalListResponse,
)
from src.versioning import InvalidVersion, Version

router = APIRouter(
    prefix="/templates",
    tags=["templates"],
    dependencies=[Depends(require_password)],
)

VALID_KINDS = ("software", "container", "image", "interaction", "binding", "connection")


def _validate_kind(kind: str) -> None:
    if kind not in VALID_KINDS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown template kind {kind!r}; valid kinds: {list(VALID_KINDS)}",
        )


async def _get_template(session: AsyncSession, kind: str, *, lock: bool = False) -> Template:
    _validate_kind(kind)
    stmt = select(Template).where(Template.kind == kind)
    if lock:
        stmt = stmt.with_for_update()
    template = (await session.execute(stmt)).scalar_one_or_none()
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template {kind!r} is not registered",
        )
    return template


async def _latest_active_template_version(
    session: AsyncSession, template_id
) -> TemplateVersion | None:
    stmt = (
        select(TemplateVersion)
        .where(TemplateVersion.template_id == template_id, TemplateVersion.status == "active")
        .order_by(
            TemplateVersion.version_major.desc(),
            TemplateVersion.version_minor.desc(),
            TemplateVersion.version_patch.desc(),
        )
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _latest_any_template_version(session: AsyncSession, template_id) -> Version | None:
    rows = (
        await session.execute(
            select(TemplateVersion).where(TemplateVersion.template_id == template_id)
        )
    ).scalars().all()
    if not rows:
        return None
    return max(
        Version(r.version_major, r.version_minor, r.version_patch, r.prerelease) for r in rows
    )


@router.get(
    "/{kind}",
    response_class=PlainTextResponse,
    responses={200: {"content": {"text/markdown": {}}}},
)
async def get_template(
    kind: str, session: AsyncSession = Depends(get_session)
) -> PlainTextResponse:
    template = await _get_template(session, kind)
    latest = await _latest_active_template_version(session, template.id)
    if latest is None:
        raise HTTPException(
            status_code=500, detail=f"Template {kind!r} has no active version"
        )
    return PlainTextResponse(latest.markdown, media_type="text/markdown")


@router.post(
    "/{kind}/proposals",
    response_model=TemplateProposalCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_template_proposal(
    kind: str,
    payload: TemplateProposalCreate,
    session: AsyncSession = Depends(get_session),
) -> TemplateProposalCreateResponse:
    template = await _get_template(session, kind, lock=True)
    new_version = Version.parse(payload.version, allow_prerelease=True)

    latest = await _latest_any_template_version(session, template.id)
    if latest is not None and not (new_version > latest):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Version {new_version} is not strictly greater than the current latest {latest}",
        )

    tv = TemplateVersion(
        template_id=template.id,
        version_major=new_version.major,
        version_minor=new_version.minor,
        version_patch=new_version.patch,
        prerelease=new_version.prerelease,
        markdown=payload.markdown,
        status="proposal",
    )
    session.add(tv)
    await session.commit()
    return TemplateProposalCreateResponse(kind=kind, version=str(new_version), status="proposal")


@router.get("/{kind}/proposals", response_model=TemplateProposalListResponse)
async def list_template_proposals(
    kind: str, session: AsyncSession = Depends(get_session)
) -> TemplateProposalListResponse:
    template = await _get_template(session, kind)
    latest_active = await _latest_active_template_version(session, template.id)
    active_v = (
        Version(latest_active.version_major, latest_active.version_minor, latest_active.version_patch)
        if latest_active is not None
        else None
    )

    rows = (
        await session.execute(
            select(TemplateVersion)
            .where(
                TemplateVersion.template_id == template.id,
                TemplateVersion.status == "proposal",
            )
            .order_by(
                TemplateVersion.version_major.asc(),
                TemplateVersion.version_minor.asc(),
                TemplateVersion.version_patch.asc(),
                TemplateVersion.prerelease.asc().nulls_last(),
            )
        )
    ).scalars().all()

    proposals: list[TemplateProposalEntry] = []
    for r in rows:
        v = Version(r.version_major, r.version_minor, r.version_patch, r.prerelease)
        if active_v is not None and not (v > active_v):
            continue
        proposals.append(
            TemplateProposalEntry(version=str(v), markdown=r.markdown, created_at=r.created_at)
        )

    return TemplateProposalListResponse(
        kind=kind,
        active_version=str(active_v) if active_v else None,
        proposals=proposals,
    )


@router.post(
    "/{kind}/proposals/{version}/accept",
    response_model=TemplateProposalAcceptResponse,
)
async def accept_template_proposal(
    kind: str,
    version: str,
    session: AsyncSession = Depends(get_session),
) -> TemplateProposalAcceptResponse:
    template = await _get_template(session, kind, lock=True)

    try:
        target = Version.parse(version, allow_prerelease=True)
    except InvalidVersion as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )

    stmt = select(TemplateVersion).where(
        TemplateVersion.template_id == template.id,
        TemplateVersion.version_major == target.major,
        TemplateVersion.version_minor == target.minor,
        TemplateVersion.version_patch == target.patch,
        TemplateVersion.prerelease.is_(target.prerelease)
        if target.prerelease is None
        else TemplateVersion.prerelease == target.prerelease,
    )
    proposal_row = (await session.execute(stmt)).scalar_one_or_none()
    if proposal_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Proposal {target} not found"
        )
    if proposal_row.status != "proposal":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Version {target} is not in 'proposal' status",
        )

    now = datetime.now(timezone.utc)

    if not target.is_prerelease:
        proposal_row.status = "active"
        proposal_row.accepted_at = now
        await session.commit()
        return TemplateProposalAcceptResponse(
            kind=kind,
            promoted_from_version=str(target),
            active_version=str(target),
            accepted_at=now,
        )

    stable = target.stable()
    existing_stable = (
        await session.execute(
            select(TemplateVersion).where(
                TemplateVersion.template_id == template.id,
                TemplateVersion.version_major == stable.major,
                TemplateVersion.version_minor == stable.minor,
                TemplateVersion.version_patch == stable.patch,
                TemplateVersion.prerelease.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing_stable is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A stable {stable} already exists; cannot promote {target}",
        )

    new_active = TemplateVersion(
        template_id=template.id,
        version_major=stable.major,
        version_minor=stable.minor,
        version_patch=stable.patch,
        prerelease=None,
        markdown=proposal_row.markdown,
        status="active",
        accepted_at=now,
        promoted_from_prerelease=target.prerelease,
    )
    session.add(new_active)
    await session.commit()

    return TemplateProposalAcceptResponse(
        kind=kind,
        promoted_from_version=str(target),
        active_version=str(stable),
        accepted_at=now,
    )
