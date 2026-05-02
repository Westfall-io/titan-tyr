from __future__ import annotations

import re
import uuid
from datetime import datetime
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.versioning import InvalidVersion, Version

VERSION_PATTERN_STABLE = r"^\d+\.\d+\.\d+$"
VERSION_PATTERN_ANY = r"^\d+\.\d+\.\d+(-rc\d+)?$"

# Software names appear in URL paths and inside contract markdown — keep them
# slug-safe: lowercase letters, digits, hyphens; no leading/trailing hyphen;
# 1-64 chars total.
SOFTWARE_NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")


def _validate_software_name(v: str) -> str:
    if not SOFTWARE_NAME_PATTERN.fullmatch(v):
        raise ValueError(
            "must be a slug: lowercase letters, digits, hyphens; "
            "1-64 chars; cannot start or end with a hyphen"
        )
    return v


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


def _validate_https_url_optional(v: str | None) -> str | None:
    if v is None:
        return v
    parsed = urlparse(v)
    if parsed.scheme != "https":
        raise ValueError("must be an https:// URL")
    if not parsed.netloc:
        raise ValueError("must include a host")
    return v


def _validate_repo_uri_on_update(v: str | None) -> str | None:
    # repo_uri is required at registration and cannot be cleared. Omit the
    # field on PUT to leave it unchanged; explicit null and empty string
    # both 422.
    if v is None:
        raise ValueError("repo_uri may not be null on update; omit the field to leave it unchanged")
    if not v:
        raise ValueError("repo_uri may not be empty")
    return v


# ---------- Software ----------


class SoftwareCreate(BaseModel):
    name: str = Field(min_length=1)
    repo_uri: str = Field(min_length=1)
    issue_tracker_uri: str | None = None
    markdown: str
    version: str = "1.0.0"

    _v = field_validator("version")(_validate_stable)
    _n = field_validator("name")(_validate_software_name)
    _it = field_validator("issue_tracker_uri")(_validate_https_url_optional)


class SoftwareCreateResponse(BaseModel):
    id: uuid.UUID
    name: str
    version: str


class SoftwareUpdate(BaseModel):
    markdown: str
    version: str
    repo_uri: str | None = None
    issue_tracker_uri: str | None = None

    _v = field_validator("version")(_validate_stable)
    _r = field_validator("repo_uri")(_validate_repo_uri_on_update)
    _it = field_validator("issue_tracker_uri")(_validate_https_url_optional)


class SoftwareUpdateResponse(BaseModel):
    name: str
    version: str


class SoftwareDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    repo_uri: str
    issue_tracker_uri: str | None
    version: str
    markdown: str
    updated_at: datetime


class SoftwareListItem(BaseModel):
    id: uuid.UUID
    name: str
    repo_uri: str
    issue_tracker_uri: str | None
    version: str
    updated_at: datetime


class SoftwareListResponse(BaseModel):
    results: list[SoftwareListItem]
    next: str | None


class ContractListItem(BaseModel):
    contract_id: uuid.UUID
    owner: str
    counterparty: str
    version: str
    updated_at: datetime


class ContractListResponse(BaseModel):
    results: list[ContractListItem]
    next: str | None


class SoftwareContractsListResponse(BaseModel):
    software: str
    results: list[ContractListItem]
    next: str | None


# ---------- Contracts ----------


class ContractCreate(BaseModel):
    owner_software: str
    counterparty_software: str
    markdown: str
    version: str = "1.0.0"

    _v = field_validator("version")(_validate_stable)
    _o = field_validator("owner_software")(_validate_software_name)
    _c = field_validator("counterparty_software")(_validate_software_name)


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


# ---------- Template proposals ----------


class TemplateProposalCreate(BaseModel):
    markdown: str
    version: str

    _v = field_validator("version")(_validate_any)


class TemplateProposalCreateResponse(BaseModel):
    kind: str
    version: str
    status: str


class TemplateProposalEntry(BaseModel):
    version: str
    markdown: str
    created_at: datetime


class TemplateProposalListResponse(BaseModel):
    kind: str
    active_version: str | None
    proposals: list[TemplateProposalEntry]


class TemplateProposalAcceptResponse(BaseModel):
    kind: str
    promoted_from_version: str
    active_version: str
    accepted_at: datetime
