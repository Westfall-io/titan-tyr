"""initial-creation attribution on parts and contracts (#39)

Closes the attribution gap left by #38: every subsequent change to a
part or contract is now attributed (proposer + acceptor on content
proposals, proposer + acceptor on shifts), but the initial
registration via POST /parts / POST /contracts was anonymous.

Adds nullable `created_by_actor` columns. POST /parts and
POST /contracts read the X-Actor request header and store it on the
new row. No backfill — pre-v0.16.0 rows continue to surface as
`null`.

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-03
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "parts",
        sa.Column("created_by_actor", sa.String(), nullable=True),
    )
    op.add_column(
        "contracts",
        sa.Column("created_by_actor", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("contracts", "created_by_actor")
    op.drop_column("parts", "created_by_actor")
