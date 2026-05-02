from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import require_password
from src.db import get_session
from src.models import Contract, ContractVersion, Software, SoftwareVersion
from src.schemas import (
    ContractEntry,
    SoftwareContractsResponse,
    SoftwareCreate,
    SoftwareCreateResponse,
    SoftwareDetail,
    SoftwareUpdate,
    SoftwareUpdateResponse,
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

    # PATCH semantics: an absent issue_tracker_uri leaves the row unchanged.
    # An explicit null clears it; an explicit string updates it.
    if "issue_tracker_uri" in payload.model_fields_set:
        software.issue_tracker_uri = payload.issue_tracker_uri

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


@router.get("/{name}/contracts", response_model=SoftwareContractsResponse)
async def list_software_contracts(
    name: str,
    session: AsyncSession = Depends(get_session),
) -> SoftwareContractsResponse:
    software = (
        await session.execute(select(Software).where(Software.name == name))
    ).scalar_one_or_none()
    if software is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Software {name!r} not found")

    stmt = select(Contract).where(
        or_(
            Contract.owner_software_id == software.id,
            Contract.counterparty_software_id == software.id,
        )
    )
    contracts = (await session.execute(stmt)).scalars().all()

    entries: list[ContractEntry] = []
    for contract in contracts:
        latest = await _latest_active_contract_version(session, contract.id)
        if latest is None:
            continue  # contract has no active version yet — skip
        owner = (await session.get(Software, contract.owner_software_id)).name
        counterparty = (await session.get(Software, contract.counterparty_software_id)).name
        entries.append(
            ContractEntry(
                id=contract.id,
                owner=owner,
                counterparty=counterparty,
                version=str(Version(latest.version_major, latest.version_minor, latest.version_patch)),
                markdown=latest.markdown,
                updated_at=latest.accepted_at or latest.created_at,
            )
        )
    return SoftwareContractsResponse(software=software.name, contracts=entries)


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
