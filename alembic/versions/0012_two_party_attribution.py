"""two-party rule attribution on content + template proposals (#38)

Extends the two-party rule shipped in #33 (subtype-shift endpoints
only) to the four endpoints that currently bypass it: content
proposals on contracts and templates. Adds nullable proposer_actor /
acceptor_actor columns and a single_operator_override boolean to
`contract_versions` and `template_versions`. Backfills no rows;
existing version rows surface as anonymous (`NULL` actors), which
the accept-time rule treats as "unenforceable, allow".

Also adds `single_operator_override` to the existing
`part_subtype_proposals` and `contract_subtype_proposals` tables so
the bypass surfaces in the audit trail. The override has been
honored since #33; it just wasn't recorded.

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-03
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------- Phase 1: contract_versions attribution columns ----------
    op.add_column(
        "contract_versions",
        sa.Column("proposer_actor", sa.String(), nullable=True),
    )
    op.add_column(
        "contract_versions",
        sa.Column("acceptor_actor", sa.String(), nullable=True),
    )
    op.add_column(
        "contract_versions",
        sa.Column(
            "single_operator_override",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # ---------- Phase 2: template_versions attribution columns ----------
    op.add_column(
        "template_versions",
        sa.Column("proposer_actor", sa.String(), nullable=True),
    )
    op.add_column(
        "template_versions",
        sa.Column("acceptor_actor", sa.String(), nullable=True),
    )
    op.add_column(
        "template_versions",
        sa.Column(
            "single_operator_override",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # ---------- Phase 3: shift-table override flag (consistency) ----------
    # The override has been honored on the shift accept endpoints since
    # #33 but was not recorded. Add the column so the audit trail
    # surfaces it on the existing shift proposals too.
    op.add_column(
        "part_subtype_proposals",
        sa.Column(
            "single_operator_override",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "contract_subtype_proposals",
        sa.Column(
            "single_operator_override",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("contract_subtype_proposals", "single_operator_override")
    op.drop_column("part_subtype_proposals", "single_operator_override")

    op.drop_column("template_versions", "single_operator_override")
    op.drop_column("template_versions", "acceptor_actor")
    op.drop_column("template_versions", "proposer_actor")

    op.drop_column("contract_versions", "single_operator_override")
    op.drop_column("contract_versions", "acceptor_actor")
    op.drop_column("contract_versions", "proposer_actor")
