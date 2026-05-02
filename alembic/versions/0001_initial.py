"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-30
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "software",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("repo_uri", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("name", name="uq_software_name"),
    )

    op.create_table(
        "software_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("software_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_major", sa.Integer(), nullable=False),
        sa.Column("version_minor", sa.Integer(), nullable=False),
        sa.Column("version_patch", sa.Integer(), nullable=False),
        sa.Column("markdown", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["software_id"],
            ["software.id"],
            ondelete="CASCADE",
            name="fk_software_versions_software_id_software",
        ),
        sa.UniqueConstraint(
            "software_id",
            "version_major",
            "version_minor",
            "version_patch",
            name="uq_software_versions_software_id_version_major_version_minor_version_patch",
        ),
        sa.CheckConstraint("version_major >= 0", name="ck_software_versions_version_major_nonneg"),
        sa.CheckConstraint("version_minor >= 0", name="ck_software_versions_version_minor_nonneg"),
        sa.CheckConstraint("version_patch >= 0", name="ck_software_versions_version_patch_nonneg"),
    )
    op.execute(
        "CREATE INDEX ix_software_versions_software_id_version "
        "ON software_versions (software_id, version_major DESC, version_minor DESC, version_patch DESC)"
    )

    op.create_table(
        "contracts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("owner_software_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("counterparty_software_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["owner_software_id"],
            ["software.id"],
            name="fk_contracts_owner_software_id_software",
        ),
        sa.ForeignKeyConstraint(
            ["counterparty_software_id"],
            ["software.id"],
            name="fk_contracts_counterparty_software_id_software",
        ),
        sa.UniqueConstraint(
            "owner_software_id",
            "counterparty_software_id",
            name="uq_contracts_owner_software_id_counterparty_software_id",
        ),
        sa.CheckConstraint(
            "owner_software_id <> counterparty_software_id",
            name="ck_contracts_owner_ne_counterparty",
        ),
    )

    op.create_table(
        "contract_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("contract_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_major", sa.Integer(), nullable=False),
        sa.Column("version_minor", sa.Integer(), nullable=False),
        sa.Column("version_patch", sa.Integer(), nullable=False),
        sa.Column("prerelease", sa.String(), nullable=True),
        sa.Column("markdown", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("promoted_from_prerelease", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["contract_id"],
            ["contracts.id"],
            ondelete="CASCADE",
            name="fk_contract_versions_contract_id_contracts",
        ),
        sa.CheckConstraint("version_major >= 0", name="ck_contract_versions_version_major_nonneg"),
        sa.CheckConstraint("version_minor >= 0", name="ck_contract_versions_version_minor_nonneg"),
        sa.CheckConstraint("version_patch >= 0", name="ck_contract_versions_version_patch_nonneg"),
        sa.CheckConstraint(
            "status IN ('active', 'proposal')", name="ck_contract_versions_status_allowed"
        ),
        sa.CheckConstraint(
            "prerelease IS NULL OR prerelease ~ '^rc[0-9]+$'",
            name="ck_contract_versions_prerelease_grammar",
        ),
        sa.CheckConstraint(
            "status = 'proposal' OR prerelease IS NULL",
            name="ck_contract_versions_active_must_be_stable",
        ),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_contract_versions_contract_id_version_prerelease "
        "ON contract_versions (contract_id, version_major, version_minor, version_patch, prerelease) "
        "NULLS NOT DISTINCT"
    )
    op.execute(
        "CREATE INDEX ix_contract_versions_contract_id_version "
        "ON contract_versions "
        "(contract_id, version_major DESC, version_minor DESC, version_patch DESC, prerelease DESC NULLS FIRST)"
    )
    op.execute(
        "CREATE INDEX ix_contract_versions_contract_id_status "
        "ON contract_versions (contract_id, status)"
    )


def downgrade() -> None:
    op.drop_table("contract_versions")
    op.drop_table("contracts")
    op.drop_table("software_versions")
    op.drop_table("software")
