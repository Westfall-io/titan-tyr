from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.versioning import InvalidVersion, Version

VERSION_PATTERN_STABLE = r"^\d+\.\d+\.\d+$"
VERSION_PATTERN_ANY = r"^\d+\.\d+\.\d+(-rc\d+)?$"


def _validate_stable(v: str) -> str:
    try:
        Version.parse(v, allow_prerelease=False)
    except InvalidVersion as exc:
        raise ValueError(str(exc)) from exc
    return v


def _validate_any(v: str) -> str:
    try:
        Version.parse(v, allow_prerelease=True)
    except InvalidVersion as exc:
        raise ValueError(str(exc)) from exc
    return v


# ---------- Software ----------


class SoftwareCreate(BaseModel):
    name: str = Field(min_length=1)
    repo_uri: str = Field(min_length=1)
    markdown: str
    version: str = "1.0.0"

    _v = field_validator("version")(_validate_stable)


class SoftwareCreateResponse(BaseModel):
    id: uuid.UUID
    name: str
    version: str


class SoftwareUpdate(BaseModel):
    markdown: str
    version: str

    _v = field_validator("version")(_validate_stable)


class SoftwareUpdateResponse(BaseModel):
    name: str
    version: str


class SoftwareDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    repo_uri: str
    version: str
    markdown: str
    updated_at: datetime


class ContractEntry(BaseModel):
    id: uuid.UUID
    owner: str
    counterparty: str
    version: str
    markdown: str
    updated_at: datetime


class SoftwareContractsResponse(BaseModel):
    software: str
    contracts: list[ContractEntry]


# ---------- Contracts ----------


class ContractCreate(BaseModel):
    owner_software: str
    counterparty_software: str
    markdown: str
    version: str = "1.0.0"

    _v = field_validator("version")(_validate_stable)


class ContractCreateResponse(BaseModel):
    contract_id: uuid.UUID
    owner: str
    counterparty: str
    version: str
    status: str


class ContractSearchResult(BaseModel):
    contract_id: uuid.UUID
    owner: str
    counterparty: str
    version: str
    markdown: str
    updated_at: datetime


class ContractSearchResponse(BaseModel):
    results: list[ContractSearchResult]


class ContractDetail(BaseModel):
    contract_id: uuid.UUID
    owner: str
    counterparty: str
    version: str
    markdown: str
    updated_at: datetime


# ---------- Proposals ----------


class ProposalCreate(BaseModel):
    markdown: str
    version: str

    _v = field_validator("version")(_validate_any)


class ProposalCreateResponse(BaseModel):
    contract_id: uuid.UUID
    version: str
    status: str


class ProposalEntry(BaseModel):
    version: str
    markdown: str
    created_at: datetime


class ProposalListResponse(BaseModel):
    contract_id: uuid.UUID
    active_version: str | None
    proposals: list[ProposalEntry]


class ProposalAcceptResponse(BaseModel):
    contract_id: uuid.UUID
    promoted_from_version: str
    active_version: str
    accepted_at: datetime
