"""contract deletion via two-party proposal flow (#69)

Mirrors the propose/accept pattern from #45's endpoint-shift for a new
structural axis: deletion. A contract row is never hard-deleted —
acceptance sets `deleted_at` plus the proposer / acceptor / rationale
columns. Read endpoints hide soft-deleted rows by default and surface
them only on `?include_deleted=true` opt-in; write endpoints (PUT,
shifts, body proposals, deletion-proposals) treat a soft-deleted row
as 404. The proposal row itself persists so the audit trail reads
back as a complete sequence.

Two new history `kind` discriminator values: `deletion_proposed`
(emitted at proposal `created_at`) and `deletion_accepted` (emitted
at proposal `accepted_at`). Both surface on
`/contracts/{id}/history?include_deleted=true`.

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-04
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------- Phase 1: soft-delete bookkeeping on contracts ----------
    # `deleted_at` is the load-bearing flag — every read query that
    # should hide soft-deleted rows filters on `deleted_at IS NULL`.
    # The proposer/acceptor/rationale columns mirror the proposal row
    # they were copied from; storing them on the contract row lets
    # restoration tooling and audit queries read the cause without
    # re-joining to the proposals table.
    op.add_column(
        "contracts",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "contracts",
        sa.Column("deleted_by_proposer_actor", sa.String(), nullable=True),
    )
    op.add_column(
        "contracts",
        sa.Column("deleted_by_acceptor_actor", sa.String(), nullable=True),
    )
    op.add_column(
        "contracts",
        sa.Column("deletion_rationale", sa.String(), nullable=True),
    )
    op.add_column(
        "contracts",
        sa.Column(
            "deletion_single_operator_override",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # Most list/detail queries filter on `deleted_at IS NULL`. A partial
    # index on the live rows keeps the common path fast without paying
    # storage for the (rarer) deleted rows.
    op.create_index(
        "ix_contracts_live",
        "contracts",
        ["id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # Re-create the subtype-pair uniqueness key (#42) as partial-on-live.
    # Soft-deleted rows shouldn't block re-registration of the same
    # endpoints+subtype: deletion is a soft state, and the audit trail
    # already records both the deleted and the freshly-registered row
    # with their own contract_ids. Without this, the only path back to
    # a previously-deleted relationship would be a (not-yet-built)
    # restoration flow.
    op.drop_index("uq_contracts_subtype_pair", table_name="contracts")
    op.create_index(
        "uq_contracts_subtype_pair",
        "contracts",
        ["owner_part_id", "counterparty_part_id", "subtype", "connection_type"],
        unique=True,
        postgresql_nulls_not_distinct=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ---------- Phase 2: contract_deletion_proposals ----------
    op.create_table(
        "contract_deletion_proposals",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "contract_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("contracts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rationale", sa.String(), nullable=False),
        sa.Column("proposer_actor", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by", sa.String(), nullable=True),
        sa.Column(
            "single_operator_override",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.CheckConstraint(
            "status IN ('proposal', 'accepted')",
            name="ck_contract_deletion_proposals_status_allowed",
        ),
    )
    op.create_index(
        "ix_contract_deletion_proposals_contract_id_status",
        "contract_deletion_proposals",
        ["contract_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_contract_deletion_proposals_contract_id_status",
        table_name="contract_deletion_proposals",
    )
    op.drop_table("contract_deletion_proposals")

    # Restore the original total uniqueness index from #42. Downgrade
    # is only safe if no soft-deleted rows currently collide with live
    # rows on the four-column key — operator's responsibility to
    # confirm before downgrading past 0018.
    op.drop_index("uq_contracts_subtype_pair", table_name="contracts")
    op.create_index(
        "uq_contracts_subtype_pair",
        "contracts",
        ["owner_part_id", "counterparty_part_id", "subtype", "connection_type"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )

    op.drop_index("ix_contracts_live", table_name="contracts")
    op.drop_column("contracts", "deletion_single_operator_override")
    op.drop_column("contracts", "deletion_rationale")
    op.drop_column("contracts", "deleted_by_acceptor_actor")
    op.drop_column("contracts", "deleted_by_proposer_actor")
    op.drop_column("contracts", "deleted_at")
