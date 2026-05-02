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
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db import Base


class Software(Base):
    __tablename__ = "software"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    repo_uri: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    versions: Mapped[list["SoftwareVersion"]] = relationship(
        back_populates="software", cascade="all, delete-orphan", passive_deletes=True
    )


class SoftwareVersion(Base):
    __tablename__ = "software_versions"
    __table_args__ = (
        UniqueConstraint(
            "software_id", "version_major", "version_minor", "version_patch"
        ),
        Index(
            "ix_software_versions_software_id_version",
            "software_id",
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
    software_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("software.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_major: Mapped[int] = mapped_column(Integer, nullable=False)
    version_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    version_patch: Mapped[int] = mapped_column(Integer, nullable=False)
    markdown: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    software: Mapped[Software] = relationship(back_populates="versions")


class Contract(Base):
    __tablename__ = "contracts"
    __table_args__ = (
        UniqueConstraint("owner_software_id", "counterparty_software_id"),
        CheckConstraint(
            "owner_software_id <> counterparty_software_id",
            name="owner_ne_counterparty",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    owner_software_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("software.id"), nullable=False
    )
    counterparty_software_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("software.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    owner: Mapped[Software] = relationship(foreign_keys=[owner_software_id])
    counterparty: Mapped[Software] = relationship(foreign_keys=[counterparty_software_id])
    versions: Mapped[list["ContractVersion"]] = relationship(
        back_populates="contract", cascade="all, delete-orphan", passive_deletes=True
    )


class ContractVersion(Base):
    __tablename__ = "contract_versions"
    __table_args__ = (
        # NULLS NOT DISTINCT requires PG 15+; this is the canonical schema.
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
