"""project tagging on parts and contracts (#44)

Adds a first-class `projects` table and nullable `project_id` foreign keys
on `parts` and `contracts`. Lets one titan-tyr database hold multiple
projects' worth of graph and lets consumers (titan-mimiron, agents)
filter to one project at a time.

Membership is single-project (one project_id per row, not a junction
table) and optional (NULL = unprojected). Existing rows get NULL and
keep working; the UI default of "show all" is unchanged.

Project metadata is minimal: name (slug) + optional description +
created_at + created_by_actor (mirrors the #39 attribution pattern).
No deletion endpoint — projects accumulate; archive semantics deferred.

Revision ID: 0015
Revises: 0014
Create Date: 2026-05-04
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("created_by_actor", sa.String(), nullable=True),
        sa.UniqueConstraint("name", name="uq_projects_name"),
    )

    op.add_column(
        "parts",
        sa.Column(
            "project_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=True,
        ),
    )
    op.create_index("ix_parts_project_id", "parts", ["project_id"])

    op.add_column(
        "contracts",
        sa.Column(
            "project_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=True,
        ),
    )
    op.create_index("ix_contracts_project_id", "contracts", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_contracts_project_id", table_name="contracts")
    op.drop_column("contracts", "project_id")
    op.drop_index("ix_parts_project_id", table_name="parts")
    op.drop_column("parts", "project_id")
    op.drop_table("projects")
