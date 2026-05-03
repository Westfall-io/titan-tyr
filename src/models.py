from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
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


class Part(Base):
    __tablename__ = "parts"
    __table_args__ = (
        CheckConstraint(
            "subtype IN ('software', 'container')",
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

    versions: Mapped[list["PartVersion"]] = relationship(
        back_populates="part", cascade="all, delete-orphan", passive_deletes=True
    )


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
        UniqueConstraint("owner_part_id", "counterparty_part_id"),
        CheckConstraint(
            "owner_part_id <> counterparty_part_id",
            name="owner_ne_counterparty",
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    owner: Mapped[Part] = relationship(foreign_keys=[owner_part_id])
    counterparty: Mapped[Part] = relationship(foreign_keys=[counterparty_part_id])
    versions: Mapped[list["ContractVersion"]] = relationship(
        back_populates="contract", cascade="all, delete-orphan", passive_deletes=True
    )


class Template(Base):
    __tablename__ = "templates"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('software', 'contract', 'container')", name="kind_allowed"
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

    contract: Mapped[Contract] = relationship(back_populates="versions")
