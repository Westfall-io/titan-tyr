from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db import Base


class Project(Base):
    """A project tag (#44).

    Lets one titan-tyr database hold multiple projects' worth of parts
    and contracts. A part or contract carries at most one `project_id`;
    NULL means "unprojected" and is the legacy default. Project
    membership filters list endpoints (`?project=<slug>`) so the UI can
    scope to one project at a time.
    """

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by_actor: Mapped[str | None] = mapped_column(String, nullable=True)


class Part(Base):
    __tablename__ = "parts"
    __table_args__ = (
        CheckConstraint(
            "subtype IN ('software', 'container', 'image', 'pod', 'compose')",
            name="ck_parts_subtype_allowed",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    subtype: Mapped[str] = mapped_column(String, nullable=False)
    repo_uri: Mapped[str] = mapped_column(String, nullable=False)
    issue_tracker_uri: Mapped[str | None] = mapped_column(String, nullable=True)
    aliases: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        server_default=text("'{}'::text[]"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Subtype-shift bookkeeping (#33). Populated on the most recent
    # accepted PartSubtypeProposal; nullable so unshifted parts have
    # no value. See part_subtype_proposals for the full timeline.
    subtype_shifted_from: Mapped[str | None] = mapped_column(String, nullable=True)
    subtype_shifted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Initial-creation attribution (#39). The X-Actor recorded at
    # POST /parts time. Nullable because pre-v0.16.0 rows have no
    # value, and because callers can register without setting the
    # header (rule unenforceable, paper trail just goes blank).
    created_by_actor: Mapped[str | None] = mapped_column(String, nullable=True)
    # Project tag (#44). NULL = unprojected (the legacy default).
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True
    )
    # Name-shift bookkeeping (#45). Populated on the most recent
    # accepted PartNameProposal; nullable so unshifted parts have no
    # value. The full timeline lives in part_name_proposals.
    name_shifted_from: Mapped[str | None] = mapped_column(String, nullable=True)
    name_shifted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    versions: Mapped[list["PartVersion"]] = relationship(
        back_populates="part", cascade="all, delete-orphan", passive_deletes=True
    )
    subtype_proposals: Mapped[list["PartSubtypeProposal"]] = relationship(
        back_populates="part", cascade="all, delete-orphan", passive_deletes=True
    )
    name_proposals: Mapped[list["PartNameProposal"]] = relationship(
        back_populates="part", cascade="all, delete-orphan", passive_deletes=True
    )
    project: Mapped[Project | None] = relationship(foreign_keys=[project_id])


class PartVersion(Base):
    __tablename__ = "part_versions"
    __table_args__ = (
        UniqueConstraint(
            "part_id",
            "version_major",
            "version_minor",
            "version_patch",
            name="uq_part_versions_version",
        ),
        Index(
            "ix_part_versions_part_id_version",
            "part_id",
            text("version_major DESC"),
            text("version_minor DESC"),
            text("version_patch DESC"),
        ),
        CheckConstraint("version_major >= 0", name="version_major_nonneg"),
        CheckConstraint("version_minor >= 0", name="version_minor_nonneg"),
        CheckConstraint("version_patch >= 0", name="version_patch_nonneg"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    part_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("parts.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_major: Mapped[int] = mapped_column(Integer, nullable=False)
    version_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    version_patch: Mapped[int] = mapped_column(Integer, nullable=False)
    markdown: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    part: Mapped[Part] = relationship(back_populates="versions")


class Contract(Base):
    __tablename__ = "contracts"
    __table_args__ = (
        # Subtype-aware uniqueness (#42). `connection_type` is NULL for
        # `interaction` and `binding` rows; with NULLS NOT DISTINCT this
        # key enforces one interaction + one binding + one connection
        # *per* connection_type per directed pair. Explicit short index
        # name avoids the 63-char Postgres identifier limit the
        # auto-generated `uq_contracts_<all-four-cols>` would exceed.
        # Partial-on-live (#69): soft-deleted rows are excluded so the
        # same endpoints+subtype can be re-registered after deletion.
        Index(
            "uq_contracts_subtype_pair",
            "owner_part_id",
            "counterparty_part_id",
            "subtype",
            "connection_type",
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # Live-row partial index (#69): keeps the common
        # `WHERE deleted_at IS NULL` lookup fast without paying storage
        # for the rarer deleted rows.
        Index(
            "ix_contracts_live",
            "id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        CheckConstraint(
            "owner_part_id <> counterparty_part_id",
            name="owner_ne_counterparty",
        ),
        CheckConstraint(
            "subtype IN ('interaction', 'binding', 'connection')",
            name="ck_contracts_subtype_allowed",
        ),
        CheckConstraint(
            "(subtype = 'connection' AND connection_type IS NOT NULL) "
            "OR (subtype <> 'connection' AND connection_type IS NULL)",
            name="ck_contracts_connection_type_required",
        ),
        CheckConstraint(
            "connection_type IS NULL OR connection_type IN "
            "('builds-from', 'instantiates', 'runs', "
            "'member-of', 'depends-on', 'submodule', 'serves-static')",
            name="ck_contracts_connection_type_allowed",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    owner_part_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("parts.id"), nullable=False
    )
    counterparty_part_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("parts.id"), nullable=False
    )
    subtype: Mapped[str] = mapped_column(String, nullable=False)
    connection_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Subtype-shift bookkeeping (#33). Populated on the most recent
    # accepted ContractSubtypeProposal; nullable so unshifted contracts
    # have no value. The `from` columns capture both subtype and
    # connection_type so a contract that shifted away from `connection`
    # retains its prior label for the audit trail.
    subtype_shifted_from: Mapped[str | None] = mapped_column(String, nullable=True)
    connection_type_shifted_from: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    subtype_shifted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Initial-creation attribution (#39). The X-Actor recorded at
    # POST /contracts time. Nullable for the same reasons as on parts.
    created_by_actor: Mapped[str | None] = mapped_column(String, nullable=True)
    # Project tag (#44). Independent of the endpoints' projects: a
    # contract can cross-cut projects, in which case it's tagged with
    # whichever project owns the relationship rather than auto-inheriting
    # from owner_part. NULL = unprojected.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True, index=True
    )
    # Endpoint-shift bookkeeping (#45). Populated on the most recent
    # accepted ContractEndpointProposal. Either name may be NULL on a
    # one-sided shift (only owner changed, or only counterparty changed).
    # Stored as names rather than ids because the audit trail is human-
    # facing and ids are opaque.
    endpoint_shifted_from_owner: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    endpoint_shifted_from_counterparty: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    endpoint_shifted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Soft-delete bookkeeping (#69). `deleted_at` is the load-bearing
    # flag — every list / detail query that should hide deleted rows
    # filters on `deleted_at IS NULL`. The proposer / acceptor /
    # rationale / override columns are copies of the deletion-proposal
    # row that landed; storing them on the contract row lets restoration
    # tooling and audit reads inspect the cause without re-joining.
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_by_proposer_actor: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    deleted_by_acceptor_actor: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    deletion_rationale: Mapped[str | None] = mapped_column(String, nullable=True)
    deletion_single_operator_override: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    owner: Mapped[Part] = relationship(foreign_keys=[owner_part_id])
    counterparty: Mapped[Part] = relationship(foreign_keys=[counterparty_part_id])
    project: Mapped[Project | None] = relationship(foreign_keys=[project_id])
    versions: Mapped[list["ContractVersion"]] = relationship(
        back_populates="contract", cascade="all, delete-orphan", passive_deletes=True
    )
    subtype_proposals: Mapped[list["ContractSubtypeProposal"]] = relationship(
        back_populates="contract", cascade="all, delete-orphan", passive_deletes=True
    )
    endpoint_proposals: Mapped[list["ContractEndpointProposal"]] = relationship(
        back_populates="contract", cascade="all, delete-orphan", passive_deletes=True
    )
    deletion_proposals: Mapped[list["ContractDeletionProposal"]] = relationship(
        back_populates="contract", cascade="all, delete-orphan", passive_deletes=True
    )


class Template(Base):
    __tablename__ = "templates"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('software', 'container', 'image', 'pod', 'compose', 'interaction', 'binding', 'connection')",
            name="kind_allowed",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    kind: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    versions: Mapped[list["TemplateVersion"]] = relationship(
        back_populates="template", cascade="all, delete-orphan", passive_deletes=True
    )


class TemplateVersion(Base):
    __tablename__ = "template_versions"
    __table_args__ = (
        Index(
            "uq_template_versions_template_id_version_prerelease",
            "template_id",
            "version_major",
            "version_minor",
            "version_patch",
            "prerelease",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        Index(
            "ix_template_versions_template_id_version",
            "template_id",
            text("version_major DESC"),
            text("version_minor DESC"),
            text("version_patch DESC"),
            text("prerelease DESC NULLS FIRST"),
        ),
        Index("ix_template_versions_template_id_status", "template_id", "status"),
        CheckConstraint("version_major >= 0", name="version_major_nonneg"),
        CheckConstraint("version_minor >= 0", name="version_minor_nonneg"),
        CheckConstraint("version_patch >= 0", name="version_patch_nonneg"),
        CheckConstraint("status IN ('active', 'proposal')", name="status_allowed"),
        CheckConstraint(
            "prerelease IS NULL OR prerelease ~ '^rc[0-9]+$'",
            name="prerelease_grammar",
        ),
        CheckConstraint(
            "status = 'proposal' OR prerelease IS NULL",
            name="active_must_be_stable",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_major: Mapped[int] = mapped_column(Integer, nullable=False)
    version_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    version_patch: Mapped[int] = mapped_column(Integer, nullable=False)
    prerelease: Mapped[str | None] = mapped_column(String, nullable=True)
    markdown: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    promoted_from_prerelease: Mapped[str | None] = mapped_column(String, nullable=True)
    proposer_actor: Mapped[str | None] = mapped_column(String, nullable=True)
    acceptor_actor: Mapped[str | None] = mapped_column(String, nullable=True)
    single_operator_override: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    template: Mapped[Template] = relationship(back_populates="versions")


class ContractVersion(Base):
    __tablename__ = "contract_versions"
    __table_args__ = (
        Index(
            "uq_contract_versions_contract_id_version_prerelease",
            "contract_id",
            "version_major",
            "version_minor",
            "version_patch",
            "prerelease",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        Index(
            "ix_contract_versions_contract_id_version",
            "contract_id",
            text("version_major DESC"),
            text("version_minor DESC"),
            text("version_patch DESC"),
            text("prerelease DESC NULLS FIRST"),
        ),
        Index("ix_contract_versions_contract_id_status", "contract_id", "status"),
        CheckConstraint("version_major >= 0", name="version_major_nonneg"),
        CheckConstraint("version_minor >= 0", name="version_minor_nonneg"),
        CheckConstraint("version_patch >= 0", name="version_patch_nonneg"),
        CheckConstraint("status IN ('active', 'proposal')", name="status_allowed"),
        CheckConstraint(
            "prerelease IS NULL OR prerelease ~ '^rc[0-9]+$'",
            name="prerelease_grammar",
        ),
        CheckConstraint(
            "status = 'proposal' OR prerelease IS NULL",
            name="active_must_be_stable",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contracts.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_major: Mapped[int] = mapped_column(Integer, nullable=False)
    version_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    version_patch: Mapped[int] = mapped_column(Integer, nullable=False)
    prerelease: Mapped[str | None] = mapped_column(String, nullable=True)
    markdown: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    promoted_from_prerelease: Mapped[str | None] = mapped_column(String, nullable=True)
    proposer_actor: Mapped[str | None] = mapped_column(String, nullable=True)
    acceptor_actor: Mapped[str | None] = mapped_column(String, nullable=True)
    single_operator_override: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    contract: Mapped[Contract] = relationship(back_populates="versions")


# ---------- Subtype-shift proposals (#33) ----------
#
# Subtype shifts are a separate propose/accept flow from content
# (body) proposals. They mutate the row's structural discriminator —
# `parts.subtype` for parts; `contracts.subtype` (+ connection_type)
# for contracts — without touching the body or version. Two-party
# sign-off is enforced at the router layer via X-Actor headers.


class PartSubtypeProposal(Base):
    __tablename__ = "part_subtype_proposals"
    __table_args__ = (
        Index(
            "ix_part_subtype_proposals_part_id_status",
            "part_id",
            "status",
        ),
        CheckConstraint(
            "status IN ('proposal', 'accepted')",
            name="ck_part_subtype_proposals_status_allowed",
        ),
        CheckConstraint(
            "new_subtype IN ('software', 'container', 'image', 'pod', 'compose')",
            name="ck_part_subtype_proposals_new_subtype_allowed",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    part_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("parts.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Snapshot of `parts.subtype` at propose time. Useful for reconstructing
    # the impact preview after the fact and for the impact endpoint.
    current_subtype_at_propose: Mapped[str] = mapped_column(String, nullable=False)
    new_subtype: Mapped[str] = mapped_column(String, nullable=False)
    rationale: Mapped[str] = mapped_column(String, nullable=False)
    proposer_actor: Mapped[str | None] = mapped_column(String, nullable=True)
    body_realign_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    accepted_by: Mapped[str | None] = mapped_column(String, nullable=True)
    single_operator_override: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    part: Mapped[Part] = relationship(back_populates="subtype_proposals")


class ContractSubtypeProposal(Base):
    __tablename__ = "contract_subtype_proposals"
    __table_args__ = (
        Index(
            "ix_contract_subtype_proposals_contract_id_status",
            "contract_id",
            "status",
        ),
        CheckConstraint(
            "status IN ('proposal', 'accepted')",
            name="ck_contract_subtype_proposals_status_allowed",
        ),
        CheckConstraint(
            "new_subtype IN ('interaction', 'binding', 'connection')",
            name="ck_contract_subtype_proposals_new_subtype_allowed",
        ),
        CheckConstraint(
            "(new_subtype = 'connection' AND new_connection_type IS NOT NULL) "
            "OR (new_subtype <> 'connection' AND new_connection_type IS NULL)",
            name="ck_contract_subtype_proposals_connection_type_required",
        ),
        CheckConstraint(
            "new_connection_type IS NULL OR new_connection_type IN "
            "('builds-from', 'instantiates', 'runs', "
            "'member-of', 'depends-on', 'submodule', 'serves-static')",
            name="ck_contract_subtype_proposals_connection_type_allowed",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contracts.id", ondelete="CASCADE"),
        nullable=False,
    )
    current_subtype_at_propose: Mapped[str] = mapped_column(String, nullable=False)
    current_connection_type_at_propose: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    new_subtype: Mapped[str] = mapped_column(String, nullable=False)
    new_connection_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rationale: Mapped[str] = mapped_column(String, nullable=False)
    proposer_actor: Mapped[str | None] = mapped_column(String, nullable=True)
    body_realign_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    accepted_by: Mapped[str | None] = mapped_column(String, nullable=True)
    single_operator_override: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    contract: Mapped[Contract] = relationship(back_populates="subtype_proposals")


# ---------- Endpoint / name-shift proposals (#45) ----------
#
# Two more shift families mirroring the subtype-shift pattern from
# #33: a contract's `(owner, counterparty)` pair (endpoint-shift) and
# a part's `name` slug (name-shift). Same propose / accept / X-Actor
# handshake; same single-operator override surface; same `kind`-
# discriminated history entry shape (`endpoint_shift`, `name_shift`).


class PartNameProposal(Base):
    __tablename__ = "part_name_proposals"
    __table_args__ = (
        Index(
            "ix_part_name_proposals_part_id_status",
            "part_id",
            "status",
        ),
        CheckConstraint(
            "status IN ('proposal', 'accepted')",
            name="ck_part_name_proposals_status_allowed",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    part_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("parts.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Snapshot of `parts.name` at propose time. Captures the previous
    # name even if subsequent shifts rename it again.
    current_name_at_propose: Mapped[str] = mapped_column(String, nullable=False)
    new_name: Mapped[str] = mapped_column(String, nullable=False)
    rationale: Mapped[str] = mapped_column(String, nullable=False)
    proposer_actor: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    accepted_by: Mapped[str | None] = mapped_column(String, nullable=True)
    single_operator_override: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    part: Mapped[Part] = relationship(back_populates="name_proposals")


class ContractEndpointProposal(Base):
    __tablename__ = "contract_endpoint_proposals"
    __table_args__ = (
        Index(
            "ix_contract_endpoint_proposals_contract_id_status",
            "contract_id",
            "status",
        ),
        CheckConstraint(
            "status IN ('proposal', 'accepted')",
            name="ck_contract_endpoint_proposals_status_allowed",
        ),
        CheckConstraint(
            "new_owner_part_id IS NOT NULL OR new_counterparty_part_id IS NOT NULL",
            name="ck_contract_endpoint_proposals_at_least_one",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contracts.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Snapshot of the contract's endpoints (by name) at propose time.
    # Names are recorded rather than ids so the audit trail remains
    # legible if either part is later renamed.
    current_owner_at_propose: Mapped[str] = mapped_column(String, nullable=False)
    current_counterparty_at_propose: Mapped[str] = mapped_column(
        String, nullable=False
    )
    # The new endpoints. Either may be NULL — a one-sided shift only
    # changes the side that's set. The CHECK above enforces "at least
    # one is non-NULL"; the propose-time validator additionally
    # enforces "at least one is *changing* from current" so a no-op
    # propose returns 422 with a friendlier message.
    new_owner_part_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("parts.id"), nullable=True
    )
    new_counterparty_part_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("parts.id"), nullable=True
    )
    rationale: Mapped[str] = mapped_column(String, nullable=False)
    proposer_actor: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    accepted_by: Mapped[str | None] = mapped_column(String, nullable=True)
    single_operator_override: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    contract: Mapped[Contract] = relationship(back_populates="endpoint_proposals")
    new_owner: Mapped[Part | None] = relationship(foreign_keys=[new_owner_part_id])
    new_counterparty: Mapped[Part | None] = relationship(
        foreign_keys=[new_counterparty_part_id]
    )


# ---------- Deletion proposals (#69) ----------
#
# A contract is never hard-deleted. The accept handshake sets
# `contracts.deleted_at` (plus the proposer / acceptor / rationale
# bookkeeping cols) and the proposal row persists. Read endpoints
# hide soft-deleted rows by default; `?include_deleted=true` opts
# back in. The proposal itself follows the same propose/accept
# shape as the other shifts: rationale + proposer_actor + status +
# accepted_by + single_operator_override.


class ContractDeletionProposal(Base):
    __tablename__ = "contract_deletion_proposals"
    __table_args__ = (
        Index(
            "ix_contract_deletion_proposals_contract_id_status",
            "contract_id",
            "status",
        ),
        CheckConstraint(
            "status IN ('proposal', 'accepted')",
            name="ck_contract_deletion_proposals_status_allowed",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contracts.id", ondelete="CASCADE"),
        nullable=False,
    )
    rationale: Mapped[str] = mapped_column(String, nullable=False)
    proposer_actor: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    accepted_by: Mapped[str | None] = mapped_column(String, nullable=True)
    single_operator_override: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    contract: Mapped[Contract] = relationship(back_populates="deletion_proposals")
