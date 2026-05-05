"""part deletion via two-party proposal flow with human confirmation (#76)

The parts-side parallel of #69's contract deletion. A part is never
hard-deleted — acceptance soft-deletes by stamping `parts.deleted_at`
plus the proposer / acceptor / rationale columns. Read endpoints
hide soft-deleted parts by default and surface them on
`?include_deleted=true`; write endpoints (PUT, subtype/name shifts,
deletion proposals) treat a soft-deleted row as 404.

Two extra wrinkles vs the contract flow:

1. **Cascade-vs-block.** A part is a node, contracts are edges.
   Hard-block on touching live contracts is the default; the
   `?cascade=true` query param on accept opts into also soft-deleting
   each touching live contract in the same transaction (with the
   same proposer / acceptor / rationale prefixed
   `cascaded from /propose-part-deletion: ...`).

2. **Human confirmation required.** The acceptor X-Actor must not be
   in the `KNOWN_AGENT_ACTORS` allowlist (default
   `{titan-tyr, titan-archaedas}`); `?single_operator=true` is
   forbidden on part-deletion accept. Two agents bouncing the
   handshake back and forth no longer satisfies the rule. Enforced
   at the router layer; this migration only ships the schema.

The unique key on `parts.name` is recreated as partial-on-live so the
same name can be re-registered after a delete (parallel to
#69's `uq_contracts_subtype_pair` treatment).

Two new history `kind` discriminator values: `deletion_proposed`
(emitted at proposal `created_at`) and `deletion_accepted` (at
proposal `accepted_at`). Both surface on
`/parts/{name}/history?include_deleted=true`.

Revision ID: 0019
Revises: 0018
Create Date: 2026-05-05
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------- Phase 1: soft-delete bookkeeping on parts ----------
    op.add_column(
        "parts",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "parts",
        sa.Column("deleted_by_proposer_actor", sa.String(), nullable=True),
    )
    op.add_column(
        "parts",
        sa.Column("deleted_by_acceptor_actor", sa.String(), nullable=True),
    )
    op.add_column(
        "parts",
        sa.Column("deletion_rationale", sa.String(), nullable=True),
    )
    op.add_column(
        "parts",
        sa.Column(
            "deletion_single_operator_override",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # Live-row partial index (#76): keeps the common
    # `WHERE deleted_at IS NULL` lookup fast.
    op.create_index(
        "ix_parts_live",
        "parts",
        ["id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # Recreate `parts.name` uniqueness as partial-on-live so the
    # same name can be re-registered after a soft delete. The
    # original `uq_parts_name` is a UniqueConstraint (not an
    # Index), so drop the constraint then create a partial unique
    # index with the same name.
    op.drop_constraint("uq_parts_name", "parts", type_="unique")
    op.create_index(
        "uq_parts_name",
        "parts",
        ["name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ---------- Phase 2: part_deletion_proposals ----------
    op.create_table(
        "part_deletion_proposals",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "part_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("parts.id", ondelete="CASCADE"),
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
        # `single_operator_override` is structurally always false on
        # part-deletion (the router rejects ?single_operator=true with
        # 422), but the column exists for shape parity with the other
        # proposal tables and as a paper-trail breadcrumb if the
        # router rule is ever relaxed.
        sa.Column(
            "single_operator_override",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        # Capture the cascade decision made at accept time so the audit
        # trail records whether touching contracts were cascade-deleted
        # alongside the part.
        sa.Column(
            "cascade",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.CheckConstraint(
            "status IN ('proposal', 'accepted')",
            name="ck_part_deletion_proposals_status_allowed",
        ),
    )
    op.create_index(
        "ix_part_deletion_proposals_part_id_status",
        "part_deletion_proposals",
        ["part_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_part_deletion_proposals_part_id_status",
        table_name="part_deletion_proposals",
    )
    op.drop_table("part_deletion_proposals")

    # Restore the original total uniqueness constraint on parts.name.
    # Downgrade is only safe if no soft-deleted rows currently collide
    # with live rows on `name` — operator's responsibility to confirm
    # before downgrading past 0019.
    op.drop_index("uq_parts_name", table_name="parts")
    op.create_unique_constraint("uq_parts_name", "parts", ["name"])

    op.drop_index("ix_parts_live", table_name="parts")
    op.drop_column("parts", "deletion_single_operator_override")
    op.drop_column("parts", "deletion_rationale")
    op.drop_column("parts", "deleted_by_acceptor_actor")
    op.drop_column("parts", "deleted_by_proposer_actor")
    op.drop_column("parts", "deleted_at")
