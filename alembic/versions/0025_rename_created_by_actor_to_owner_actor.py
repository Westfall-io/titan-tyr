"""rename created_by_actor to owner_actor on parts, contracts, projects (#119)

Per #119: `created_by_actor` conflated two distinct concerns — an
immutable audit fact ("who registered this row") and an operational
ownership pointer ("who maintains this row now"). The conflation
forced first-write-wins backfill as the only mutability story, which
left no path to correct misattributed rows (e.g. handoff-token
slips).

This migration renames the column to `owner_actor` across all three
tables that carry it. Value preserved verbatim — the existing
"creator-of-record" value becomes the initial "owner-of-record" value.
The creator information isn't lost: it's derivable from the first
`body_bump` entry in each row's history (the version row's
`proposer_actor` IS the creator).

Tables affected: `parts`, `contracts`, `projects`. PartVersion,
ContractVersion, Template, proposal tables, agent_actors, and
auth_tokens never carried this column.

Mutability behavior change (in the router, not this migration):
first-write-wins backfill on `PUT /parts` / `PUT /contracts` is
removed. Reassignment becomes an explicit operation via the new
`PUT /parts/{name}/owner` and `PUT /contracts/{id}/owner` endpoints.
Projects keep first-write-wins (they don't get a separate `/owner`
endpoint; the `PUT /projects/{name}` semantics are unchanged).

Revision ID: 0025
Revises: 0024
Create Date: 2026-05-29
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("parts",     "created_by_actor", new_column_name="owner_actor")
    op.alter_column("contracts", "created_by_actor", new_column_name="owner_actor")
    op.alter_column("projects",  "created_by_actor", new_column_name="owner_actor")


def downgrade() -> None:
    op.alter_column("projects",  "owner_actor", new_column_name="created_by_actor")
    op.alter_column("contracts", "owner_actor", new_column_name="created_by_actor")
    op.alter_column("parts",     "owner_actor", new_column_name="created_by_actor")
