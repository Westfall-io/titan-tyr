from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import require_password
from src.db import get_session
from src.models import Contract, ContractVersion
from src.routers._subtype_helpers import enforce_two_party
from src.routers.parts import _latest_active_contract_version
from src.schemas import (
    ProposalAcceptResponse,
    ProposalCreate,
    ProposalCreateResponse,
    ProposalEntry,
    ProposalListResponse,
)
from src.versioning import InvalidVersion, Version

router = APIRouter(
    prefix="/contracts/{contract_id}/proposals",
    tags=["proposals"],
    dependencies=[Depends(require_password)],
)


async def _latest_any_version(session: AsyncSession, contract_id: uuid.UUID) -> Version | None:
    """Latest version on the contract under semver ordering, across all rows."""
    stmt = select(ContractVersion).where(ContractVersion.contract_id == contract_id)
    rows = (await session.execute(stmt)).scalars().all()
    if not rows:
        return None
    versions = [
        Version(r.version_major, r.version_minor, r.version_patch, r.prerelease) for r in rows
    ]
    return max(versions)


@router.post("", response_model=ProposalCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_proposal(
    contract_id: uuid.UUID,
    payload: ProposalCreate,
    session: AsyncSession = Depends(get_session),
    x_actor: str | None = Header(default=None, alias="X-Actor"),
) -> ProposalCreateResponse:
    contract = (
        await session.execute(
            select(Contract).where(Contract.id == contract_id).with_for_update()
        )
    ).scalar_one_or_none()
    if contract is None or contract.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found")

    new_version = Version.parse(payload.version, allow_prerelease=True)

    latest = await _latest_any_version(session, contract_id)
    if latest is not None and not (new_version > latest):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Version {new_version} is not strictly greater than the current latest {latest}",
        )

    cv = ContractVersion(
        contract_id=contract_id,
        version_major=new_version.major,
        version_minor=new_version.minor,
        version_patch=new_version.patch,
        prerelease=new_version.prerelease,
        markdown=payload.markdown,
        status="proposal",
        proposer_actor=x_actor,
    )
    session.add(cv)
    await session.commit()
    return ProposalCreateResponse(contract_id=contract_id, version=str(new_version), status="proposal")


@router.get("", response_model=ProposalListResponse)
async def list_proposals(
    contract_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> ProposalListResponse:
    contract = await session.get(Contract, contract_id)
    if contract is None or contract.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found")

    latest_active = await _latest_active_contract_version(session, contract_id)
    active_v = (
        Version(latest_active.version_major, latest_active.version_minor, latest_active.version_patch)
        if latest_active is not None
        else None
    )

    stmt = (
        select(ContractVersion)
        .where(ContractVersion.contract_id == contract_id, ContractVersion.status == "proposal")
        .order_by(
            ContractVersion.version_major.asc(),
            ContractVersion.version_minor.asc(),
            ContractVersion.version_patch.asc(),
            ContractVersion.prerelease.asc().nulls_last(),
        )
    )
    rows = (await session.execute(stmt)).scalars().all()

    proposals: list[ProposalEntry] = []
    for r in rows:
        v = Version(r.version_major, r.version_minor, r.version_patch, r.prerelease)
        if active_v is not None and not (v > active_v):
            continue
        proposals.append(
            ProposalEntry(
                version=str(v),
                markdown=r.markdown,
                created_at=r.created_at,
                proposer_actor=r.proposer_actor,
                acceptor_actor=r.acceptor_actor,
                single_operator_override=r.single_operator_override,
            )
        )

    return ProposalListResponse(
        contract_id=contract_id,
        active_version=str(active_v) if active_v else None,
        proposals=proposals,
    )


@router.post("/{version}/accept", response_model=ProposalAcceptResponse)
async def accept_proposal(
    contract_id: uuid.UUID,
    version: str,
    session: AsyncSession = Depends(get_session),
    x_actor: str | None = Header(default=None, alias="X-Actor"),
    single_operator: bool = False,
) -> ProposalAcceptResponse:
    contract = (
        await session.execute(
            select(Contract).where(Contract.id == contract_id).with_for_update()
        )
    ).scalar_one_or_none()
    if contract is None or contract.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found")

    try:
        target = Version.parse(version, allow_prerelease=True)
    except InvalidVersion as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    stmt = select(ContractVersion).where(
        ContractVersion.contract_id == contract_id,
        ContractVersion.version_major == target.major,
        ContractVersion.version_minor == target.minor,
        ContractVersion.version_patch == target.patch,
        ContractVersion.prerelease.is_(target.prerelease) if target.prerelease is None
        else ContractVersion.prerelease == target.prerelease,
    )
    proposal_row = (await session.execute(stmt)).scalar_one_or_none()
    if proposal_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Proposal {target} not found")
    if proposal_row.status != "proposal":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Version {target} is not in 'proposal' status",
        )

    enforce_two_party(
        proposer_actor=proposal_row.proposer_actor,
        acceptor_actor=x_actor,
        single_operator=single_operator,
    )

    now = datetime.now(timezone.utc)

    if not target.is_prerelease:
        proposal_row.status = "active"
        proposal_row.accepted_at = now
        proposal_row.acceptor_actor = x_actor
        proposal_row.single_operator_override = single_operator
        await session.commit()
        return ProposalAcceptResponse(
            contract_id=contract_id,
            promoted_from_version=str(target),
            active_version=str(target),
            accepted_at=now,
            proposer_actor=proposal_row.proposer_actor,
            acceptor_actor=x_actor,
            single_operator_override=single_operator,
        )

    stable = target.stable()
    existing_stable = (
        await session.execute(
            select(ContractVersion).where(
                ContractVersion.contract_id == contract_id,
                ContractVersion.version_major == stable.major,
                ContractVersion.version_minor == stable.minor,
                ContractVersion.version_patch == stable.patch,
                ContractVersion.prerelease.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing_stable is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A stable {stable} already exists; cannot promote {target}",
        )

    # Stamp the override on the RC row too (it stays as `proposal` for
    # posterity but should reflect that the bypass was used). Per the
    # ticket: the user-visible stable target carries the same flag.
    proposal_row.single_operator_override = single_operator

    new_active = ContractVersion(
        contract_id=contract_id,
        version_major=stable.major,
        version_minor=stable.minor,
        version_patch=stable.patch,
        prerelease=None,
        markdown=proposal_row.markdown,
        status="active",
        accepted_at=now,
        promoted_from_prerelease=target.prerelease,
        proposer_actor=proposal_row.proposer_actor,
        acceptor_actor=x_actor,
        single_operator_override=single_operator,
    )
    session.add(new_active)
    await session.commit()

    return ProposalAcceptResponse(
        contract_id=contract_id,
        promoted_from_version=str(target),
        active_version=str(stable),
        accepted_at=now,
        proposer_actor=proposal_row.proposer_actor,
        acceptor_actor=x_actor,
        single_operator_override=single_operator,
    )
