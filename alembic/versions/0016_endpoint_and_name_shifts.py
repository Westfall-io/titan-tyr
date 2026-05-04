"""endpoint-shift (contracts) + name-shift (parts) proposal flows (#45)

Mirrors the subtype-shift machinery from #33 for two more previously-
immutable attributes:

- A contract's `(owner_part_id, counterparty_part_id)` pair via
  `contract_endpoint_proposals` — same propose/accept/X-Actor handshake.
- A part's `name` slug via `part_name_proposals` — likewise.

Two new history `kind` discriminator values follow: `endpoint_shift`
on contract history and `name_shift` on part history. The existing
`subtype_shift` machinery is unchanged.

Both new tables follow the exact shape established by
`part_subtype_proposals` and `contract_subtype_proposals`:
proposer_actor + accepted_by + single_operator_override columns from
the start (no retrofit needed). Two bookkeeping columns on `parts`
(`name_shifted_from`, `name_shifted_at`) and three on `contracts`
(`endpoint_shifted_from_owner`, `endpoint_shifted_from_counterparty`,
`endpoint_shifted_at`) capture the most recent accepted shift for
fast reads.

Notably, contracts hold `owner_part_id` / `counterparty_part_id` as
FKs to `parts.id`. A part name change does **not** cascade to
contract rows — the FK is by id, and contract responses surface the
new name automatically on the next GET via the join. So name-shift
is a single `UPDATE parts SET name = ...`; no contract-side cascade
needed (per the foundation note on #45).

Revision ID: 0016
Revises: 0015
Create Date: 2026-05-04
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------- Phase 1: name-shift bookkeeping on parts ----------
    op.add_column(
        "parts",
        sa.Column("name_shifted_from", sa.String(), nullable=True),
    )
    op.add_column(
        "parts",
        sa.Column(
            "name_shifted_at", sa.DateTime(timezone=True), nullable=True
        ),
    )

    # ---------- Phase 2: endpoint-shift bookkeeping on contracts ----------
    # Stored as the *names* (not ids) of the prior endpoints because the
    # primary use is humans reading the audit trail. The ids would be
    # opaque; the names are more legible. Either name may be NULL on a
    # one-sided shift (only owner changed, or only counterparty changed).
    op.add_column(
        "contracts",
        sa.Column("endpoint_shifted_from_owner", sa.String(), nullable=True),
    )
    op.add_column(
        "contracts",
        sa.Column(
            "endpoint_shifted_from_counterparty", sa.String(), nullable=True
        ),
    )
    op.add_column(
        "contracts",
        sa.Column(
            "endpoint_shifted_at", sa.DateTime(timezone=True), nullable=True
        ),
    )

    # ---------- Phase 3: part_name_proposals ----------
    op.create_table(
        "part_name_proposals",
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
        sa.Column("current_name_at_propose", sa.String(), nullable=False),
        sa.Column("new_name", sa.String(), nullable=False),
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
            name="ck_part_name_proposals_status_allowed",
        ),
    )
    op.create_index(
        "ix_part_name_proposals_part_id_status",
        "part_name_proposals",
        ["part_id", "status"],
    )

    # ---------- Phase 4: contract_endpoint_proposals ----------
    # `new_owner_part_id` and `new_counterparty_part_id` are nullable —
    # at least one must be non-NULL (validated at the router layer; a
    # CHECK constraint here would conflict with the propose-time
    # validator that gives a friendlier error message).
    op.create_table(
        "contract_endpoint_proposals",
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
        # Snapshot of the contract's endpoints at propose time. The new
        # endpoints are FKs to parts.id (the API resolves slugs); the
        # snapshot stores the *names* for the audit trail in case either
        # part is later renamed.
        sa.Column("current_owner_at_propose", sa.String(), nullable=False),
        sa.Column(
            "current_counterparty_at_propose", sa.String(), nullable=False
        ),
        sa.Column(
            "new_owner_part_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("parts.id"),
            nullable=True,
        ),
        sa.Column(
            "new_counterparty_part_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("parts.id"),
            nullable=True,
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
            name="ck_contract_endpoint_proposals_status_allowed",
        ),
        sa.CheckConstraint(
            "new_owner_part_id IS NOT NULL OR new_counterparty_part_id IS NOT NULL",
            name="ck_contract_endpoint_proposals_at_least_one",
        ),
    )
    op.create_index(
        "ix_contract_endpoint_proposals_contract_id_status",
        "contract_endpoint_proposals",
        ["contract_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_contract_endpoint_proposals_contract_id_status",
        table_name="contract_endpoint_proposals",
    )
    op.drop_table("contract_endpoint_proposals")

    op.drop_index(
        "ix_part_name_proposals_part_id_status",
        table_name="part_name_proposals",
    )
    op.drop_table("part_name_proposals")

    op.drop_column("contracts", "endpoint_shifted_at")
    op.drop_column("contracts", "endpoint_shifted_from_counterparty")
    op.drop_column("contracts", "endpoint_shifted_from_owner")

    op.drop_column("parts", "name_shifted_at")
    op.drop_column("parts", "name_shifted_from")
