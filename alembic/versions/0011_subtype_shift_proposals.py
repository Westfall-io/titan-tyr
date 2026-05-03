"""subtype-shift proposal flow for parts and contracts (#33)

Adds the propose/accept machinery for shifting a row's structural
discriminator (parts: subtype; contracts: subtype + connection_type)
without rebuilding the row. The shift is recorded as a discrete
event in the version history with `kind=subtype_shift`, distinct
from a body version bump.

Two new tables hold the open and accepted proposals:

- `part_subtype_proposals`
- `contract_subtype_proposals`

Both carry a `proposer_actor` column (the X-Actor request header at
propose time) so the accept endpoint can enforce the
proposer-doesn't-accept rule (with `?single_operator=true` as an
explicit override for solo setups).

Two new nullable columns on `parts` (subtype_shifted_from,
subtype_shifted_at) and three on `contracts` (subtype_shifted_from,
connection_type_shifted_from, subtype_shifted_at) capture the most
recent accepted shift for fast reads. The full timeline lives in
the proposal tables.

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-03
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------- Phase 1: nullable shift bookkeeping on parts ----------
    op.add_column(
        "parts",
        sa.Column("subtype_shifted_from", sa.String(), nullable=True),
    )
    op.add_column(
        "parts",
        sa.Column(
            "subtype_shifted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # ---------- Phase 2: nullable shift bookkeeping on contracts ----------
    op.add_column(
        "contracts",
        sa.Column("subtype_shifted_from", sa.String(), nullable=True),
    )
    op.add_column(
        "contracts",
        sa.Column(
            "connection_type_shifted_from", sa.String(length=32), nullable=True
        ),
    )
    op.add_column(
        "contracts",
        sa.Column(
            "subtype_shifted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # ---------- Phase 3: part_subtype_proposals ----------
    op.create_table(
        "part_subtype_proposals",
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
        sa.Column("current_subtype_at_propose", sa.String(), nullable=False),
        sa.Column("new_subtype", sa.String(), nullable=False),
        sa.Column("rationale", sa.String(), nullable=False),
        sa.Column("proposer_actor", sa.String(), nullable=True),
        sa.Column(
            "body_realign_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by", sa.String(), nullable=True),
        sa.CheckConstraint(
            "status IN ('proposal', 'accepted')",
            name="ck_part_subtype_proposals_status_allowed",
        ),
        sa.CheckConstraint(
            "new_subtype IN ('software', 'container', 'image', 'pod', 'compose')",
            name="ck_part_subtype_proposals_new_subtype_allowed",
        ),
    )
    op.create_index(
        "ix_part_subtype_proposals_part_id_status",
        "part_subtype_proposals",
        ["part_id", "status"],
    )

    # ---------- Phase 4: contract_subtype_proposals ----------
    op.create_table(
        "contract_subtype_proposals",
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
        sa.Column("current_subtype_at_propose", sa.String(), nullable=False),
        sa.Column(
            "current_connection_type_at_propose",
            sa.String(length=32),
            nullable=True,
        ),
        sa.Column("new_subtype", sa.String(), nullable=False),
        sa.Column("new_connection_type", sa.String(length=32), nullable=True),
        sa.Column("rationale", sa.String(), nullable=False),
        sa.Column("proposer_actor", sa.String(), nullable=True),
        sa.Column(
            "body_realign_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by", sa.String(), nullable=True),
        sa.CheckConstraint(
            "status IN ('proposal', 'accepted')",
            name="ck_contract_subtype_proposals_status_allowed",
        ),
        sa.CheckConstraint(
            "new_subtype IN ('interaction', 'binding', 'connection')",
            name="ck_contract_subtype_proposals_new_subtype_allowed",
        ),
        sa.CheckConstraint(
            "(new_subtype = 'connection' AND new_connection_type IS NOT NULL) "
            "OR (new_subtype <> 'connection' AND new_connection_type IS NULL)",
            name="ck_contract_subtype_proposals_connection_type_required",
        ),
        sa.CheckConstraint(
            "new_connection_type IS NULL OR new_connection_type IN "
            "('builds-from', 'instantiates', 'runs', "
            "'member-of', 'depends-on', 'submodule')",
            name="ck_contract_subtype_proposals_connection_type_allowed",
        ),
    )
    op.create_index(
        "ix_contract_subtype_proposals_contract_id_status",
        "contract_subtype_proposals",
        ["contract_id", "status"],
    )


def downgrade() -> None:
    # Tables first (their FKs reference parts / contracts).
    op.drop_index(
        "ix_contract_subtype_proposals_contract_id_status",
        table_name="contract_subtype_proposals",
    )
    op.drop_table("contract_subtype_proposals")

    op.drop_index(
        "ix_part_subtype_proposals_part_id_status",
        table_name="part_subtype_proposals",
    )
    op.drop_table("part_subtype_proposals")

    # Then the bookkeeping columns on contracts.
    op.drop_column("contracts", "subtype_shifted_at")
    op.drop_column("contracts", "connection_type_shifted_from")
    op.drop_column("contracts", "subtype_shifted_from")

    # And the bookkeeping columns on parts.
    op.drop_column("parts", "subtype_shifted_at")
    op.drop_column("parts", "subtype_shifted_from")
