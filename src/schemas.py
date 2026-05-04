from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.versioning import InvalidVersion, Version

VERSION_PATTERN_STABLE = r"^\d+\.\d+\.\d+$"
VERSION_PATTERN_ANY = r"^\d+\.\d+\.\d+(-rc\d+)?$"

# Part names appear in URL paths and inside contract markdown — keep them
# slug-safe: lowercase letters, digits, hyphens; no leading/trailing hyphen;
# 1-64 chars total. (Same rule that previously applied to software names.)
PART_NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")

PART_SUBTYPES: tuple[str, ...] = ("software", "container", "image", "pod", "compose")
PartSubtype = Literal["software", "container", "image", "pod", "compose"]

CONTRACT_SUBTYPES: tuple[str, ...] = ("interaction", "binding", "connection")
ContractSubtype = Literal["interaction", "binding", "connection"]

# Connection sub-discriminator. Each label has its own From/To Part type rule
# enforced in the contracts router; the schema layer just constrains the
# enum. See docs/api.md and #32 for the full per-label rule table.
CONNECTION_TYPES: tuple[str, ...] = (
    "builds-from",
    "instantiates",
    "runs",
    "member-of",
    "depends-on",
    "submodule",
)
ConnectionType = Literal[
    "builds-from",
    "instantiates",
    "runs",
    "member-of",
    "depends-on",
    "submodule",
]


def _validate_part_name(v: str) -> str:
    if not PART_NAME_PATTERN.fullmatch(v):
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


# Aliases are colloquial labels ("front end" → admin-ui). Per #13: 1-128 chars
# after trim, reject control chars / newlines, allow Unicode (so "前端" works),
# case-preserved on storage and case-insensitive on lookup. Per-payload dedupe
# is case-insensitive ("Foo" and "foo" collapse). No cross-part uniqueness.
_ALIAS_BAD_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def _validate_aliases(v: list[str] | None) -> list[str] | None:
    if v is None:
        return v
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in v:
        if not isinstance(raw, str):
            raise ValueError("each alias must be a string")
        s = raw.strip()
        if not s:
            raise ValueError("alias may not be empty or whitespace-only")
        if len(s) > 128:
            raise ValueError("alias may not exceed 128 characters")
        if _ALIAS_BAD_CHARS.search(s):
            raise ValueError("alias may not contain control characters or newlines")
        key = s.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(s)
    return cleaned


# ---------- Projects (#44) ----------
#
# Projects are tags applied to parts and contracts so the UI and
# agents can filter the graph to one project at a time. Membership is
# single-project (one project_id per row, not a junction table) and
# optional (NULL = unprojected). Project slugs share the part-name
# slug rule but live in a separate namespace — `payments` as a
# project doesn't collide with `payments` as a part.

# Sentinel value passed via `?project=__none__` to filter a list to
# rows with NULL project_id (the "unprojected" bucket). Chosen because
# it cannot be a valid slug (contains underscores), so collision with
# a real project name is impossible.
PROJECT_NONE_SENTINEL = "__none__"


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None

    _n = field_validator("name")(_validate_part_name)


class ProjectCreateResponse(BaseModel):
    name: str
    description: str | None
    created_at: datetime
    created_by_actor: str | None = None


class ProjectUpdate(BaseModel):
    description: str | None = None


class ProjectDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    description: str | None
    created_at: datetime
    created_by_actor: str | None = None
    part_count: int = 0
    contract_count: int = 0


class ProjectListResponse(BaseModel):
    results: list[ProjectDetail]
    next: str | None


# ---------- Parts ----------
#
# Per #23 direction (3): flat schema with per-subtype validation in field
# validators, NOT a Pydantic discriminated union. Existing schemas in the repo
# are flat; staying consistent. Promote to a discriminated union if a third
# subtype lands and per-subtype divergence grows.


class PartCreate(BaseModel):
    name: str = Field(min_length=1)
    subtype: PartSubtype
    repo_uri: str = Field(min_length=1)
    issue_tracker_uri: str | None = None
    aliases: list[str] = Field(default_factory=list)
    markdown: str
    version: str = "1.0.0"
    # Optional project tag (#44). Slug of an existing project; resolves
    # to a foreign key. Omit / null = unprojected.
    project: str | None = None

    _v = field_validator("version")(_validate_stable)
    _n = field_validator("name")(_validate_part_name)
    _it = field_validator("issue_tracker_uri")(_validate_https_url_optional)
    _a = field_validator("aliases")(_validate_aliases)

    @field_validator("project")
    @classmethod
    def _project_slug(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _validate_part_name(v)


class PartCreateResponse(BaseModel):
    id: uuid.UUID
    name: str
    subtype: str
    version: str


class PartUpdate(BaseModel):
    markdown: str
    version: str
    repo_uri: str | None = None
    issue_tracker_uri: str | None = None
    aliases: list[str] | None = None
    # Project (re)assignment (#44). Omit = unchanged. Explicit null =
    # clear the project tag (move to unprojected). Slug of an existing
    # project = move to that project; 422 if the project doesn't exist.
    project: str | None = None

    _v = field_validator("version")(_validate_stable)
    _r = field_validator("repo_uri")(_validate_repo_uri_on_update)
    _it = field_validator("issue_tracker_uri")(_validate_https_url_optional)
    _a = field_validator("aliases")(_validate_aliases)

    @field_validator("project")
    @classmethod
    def _project_slug(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _validate_part_name(v)


class PartUpdateResponse(BaseModel):
    name: str
    version: str


class PartDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    subtype: str
    repo_uri: str
    issue_tracker_uri: str | None
    aliases: list[str]
    version: str
    markdown: str
    updated_at: datetime
    created_by_actor: str | None = None
    project: str | None = None


class PartListItem(BaseModel):
    id: uuid.UUID
    name: str
    subtype: str
    repo_uri: str
    issue_tracker_uri: str | None
    aliases: list[str]
    version: str
    updated_at: datetime
    created_by_actor: str | None = None
    project: str | None = None


class PartListResponse(BaseModel):
    results: list[PartListItem]
    next: str | None


class ContractListItem(BaseModel):
    contract_id: uuid.UUID
    owner: str
    counterparty: str
    subtype: ContractSubtype
    connection_type: ConnectionType | None = None
    version: str
    updated_at: datetime
    created_by_actor: str | None = None
    project: str | None = None


class ContractListResponse(BaseModel):
    results: list[ContractListItem]
    next: str | None


class PartContractsListResponse(BaseModel):
    part: str
    results: list[ContractListItem]
    next: str | None


# ---------- Contracts ----------


class ContractCreate(BaseModel):
    owner_part: str
    counterparty_part: str
    subtype: ContractSubtype
    connection_type: ConnectionType | None = None
    markdown: str
    version: str = "1.0.0"
    # Optional project tag (#44). Independent of the endpoints'
    # projects: a contract can cross-cut projects, in which case it's
    # tagged with whichever project owns the relationship.
    project: str | None = None

    _v = field_validator("version")(_validate_stable)
    _o = field_validator("owner_part")(_validate_part_name)
    _c = field_validator("counterparty_part")(_validate_part_name)

    @field_validator("project")
    @classmethod
    def _project_slug(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _validate_part_name(v)


class ContractCreateResponse(BaseModel):
    contract_id: uuid.UUID
    owner: str
    counterparty: str
    subtype: ContractSubtype
    connection_type: ConnectionType | None = None
    version: str
    status: str
    project: str | None = None


class ContractSearchResult(BaseModel):
    contract_id: uuid.UUID
    owner: str
    counterparty: str
    subtype: ContractSubtype
    connection_type: ConnectionType | None = None
    version: str
    markdown: str
    updated_at: datetime
    created_by_actor: str | None = None
    project: str | None = None


class ContractSearchResponse(BaseModel):
    results: list[ContractSearchResult]


class ContractDetail(BaseModel):
    contract_id: uuid.UUID
    owner: str
    counterparty: str
    subtype: ContractSubtype
    connection_type: ConnectionType | None = None
    version: str
    markdown: str
    updated_at: datetime
    created_by_actor: str | None = None
    project: str | None = None


# ---------- Version history ----------


class VersionHistoryItem(BaseModel):
    version: str
    updated_at: datetime
    # `kind` distinguishes a normal body version bump from a subtype shift
    # acceptance event (#33). Subtype shifts do not change the body version
    # — they record a structural transition under the same version
    # number — so the history endpoint emits both kinds in chronological
    # order with this discriminator.
    kind: Literal["body_bump", "subtype_shift"] = "body_bump"


class VersionHistoryResponse(BaseModel):
    results: list[VersionHistoryItem]
    next: str | None


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
    proposer_actor: str | None = None
    acceptor_actor: str | None = None
    single_operator_override: bool = False


class ProposalListResponse(BaseModel):
    contract_id: uuid.UUID
    active_version: str | None
    proposals: list[ProposalEntry]


class ProposalAcceptResponse(BaseModel):
    contract_id: uuid.UUID
    promoted_from_version: str
    active_version: str
    accepted_at: datetime
    proposer_actor: str | None = None
    acceptor_actor: str | None = None
    single_operator_override: bool = False


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
    proposer_actor: str | None = None
    acceptor_actor: str | None = None
    single_operator_override: bool = False


class TemplateProposalListResponse(BaseModel):
    kind: str
    active_version: str | None
    proposals: list[TemplateProposalEntry]


class TemplateProposalAcceptResponse(BaseModel):
    kind: str
    promoted_from_version: str
    active_version: str
    accepted_at: datetime
    proposer_actor: str | None = None
    acceptor_actor: str | None = None
    single_operator_override: bool = False


# ---------- Subtype-shift proposals (#33) ----------
#
# Subtype shifts are a separate propose/accept flow from content
# proposals. The body is not mutated; the row's structural
# discriminator (parts: subtype; contracts: subtype + connection_type)
# is the only thing that changes on accept. Two-party sign-off is
# enforced via the X-Actor request header (proposer's actor ≠
# acceptor's actor) with `?single_operator=true` as an explicit
# override for solo setups.


class RelatedRowAffected(BaseModel):
    """A row whose validation may break post-shift; informational only.

    Acceptance does not auto-cascade — the user files separate shift
    proposals on each affected row if needed.
    """

    contract_id: uuid.UUID | None = None
    part_name: str | None = None
    owner: str | None = None
    counterparty: str | None = None
    subtype: str
    reason: str


class SubtypeShiftImpact(BaseModel):
    body_realign_required: bool
    # `pass`/`fail` for contract shifts where the source/target rule of
    # the new subtype is checked against the row's current endpoints;
    # `n/a` for part shifts (parts have no source/target rule).
    source_target_validation: Literal["pass", "fail", "n/a"]
    related_rows_potentially_affected: list[RelatedRowAffected]


class PartSubtypeShiftCreate(BaseModel):
    new_subtype: PartSubtype
    rationale: str = Field(..., min_length=1, max_length=2000)


class PartSubtypeShiftEntry(BaseModel):
    proposal_id: uuid.UUID
    current_subtype: str
    new_subtype: str
    rationale: str
    proposer_actor: str | None
    impact: SubtypeShiftImpact
    status: Literal["proposal", "accepted"]
    created_at: datetime
    accepted_at: datetime | None = None
    accepted_by: str | None = None
    single_operator_override: bool = False


class PartSubtypeShiftCreateResponse(BaseModel):
    proposal_id: uuid.UUID
    part_name: str
    current_subtype: str
    new_subtype: str
    impact: SubtypeShiftImpact
    status: Literal["proposal"]


class PartSubtypeShiftListResponse(BaseModel):
    part_name: str
    current_subtype: str
    proposals: list[PartSubtypeShiftEntry]


class PartSubtypeShiftAcceptResponse(BaseModel):
    proposal_id: uuid.UUID
    part_name: str
    shifted_from: str
    shifted_to: str
    accepted_at: datetime
    accepted_by: str | None
    body_realign_required: bool
    single_operator_override: bool = False


class ContractSubtypeShiftCreate(BaseModel):
    new_subtype: ContractSubtype
    new_connection_type: ConnectionType | None = None
    rationale: str = Field(..., min_length=1, max_length=2000)


class ContractSubtypeShiftEntry(BaseModel):
    proposal_id: uuid.UUID
    current_subtype: str
    current_connection_type: str | None
    new_subtype: str
    new_connection_type: str | None
    rationale: str
    proposer_actor: str | None
    impact: SubtypeShiftImpact
    status: Literal["proposal", "accepted"]
    created_at: datetime
    accepted_at: datetime | None = None
    accepted_by: str | None = None
    single_operator_override: bool = False


class ContractSubtypeShiftCreateResponse(BaseModel):
    proposal_id: uuid.UUID
    contract_id: uuid.UUID
    current_subtype: str
    current_connection_type: str | None
    new_subtype: str
    new_connection_type: str | None
    impact: SubtypeShiftImpact
    status: Literal["proposal"]


class ContractSubtypeShiftListResponse(BaseModel):
    contract_id: uuid.UUID
    current_subtype: str
    current_connection_type: str | None
    proposals: list[ContractSubtypeShiftEntry]


class ContractSubtypeShiftAcceptResponse(BaseModel):
    proposal_id: uuid.UUID
    contract_id: uuid.UUID
    shifted_from_subtype: str
    shifted_to_subtype: str
    shifted_from_connection_type: str | None
    shifted_to_connection_type: str | None
    accepted_at: datetime
    accepted_by: str | None
    body_realign_required: bool
    single_operator_override: bool = False
