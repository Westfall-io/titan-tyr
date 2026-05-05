"""agent-actor registration table backing the human-confirmation gate (#78)

Replaces the hardcoded `KNOWN_AGENT_ACTORS` config default with a
DB-backed allowlist. Two reasons the config approach was wrong:

1. The defaults were stale: `{titan-tyr, titan-archaedas}` shipped in
   #76, but the actual prod actors writing today are
   `{titan-tyr, archaedas, mimiron}` — meaning the human-confirmation
   gate was bypassable by `archaedas` and `mimiron` until this
   migration seeds them in.

2. Operationally, every new project's agent required an env-var change
   plus an API restart. With multi-project onboarding starting, this
   becomes a recurring footgun.

Soft-delete pattern (revoke rather than hard-delete) preserves the
audit trail of every agent identity that has ever held the marker —
re-registering a revoked actor creates a new row rather than
resurrecting the old one, so `registered_at` always reflects the
current registration window.

Revision ID: 0020
Revises: 0019
Create Date: 2026-05-05
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_actors",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column(
            "registered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("registered_by_actor", sa.String(), nullable=True),
        sa.Column(
            "revoked_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("revoked_by_actor", sa.String(), nullable=True),
        sa.Column("revoke_rationale", sa.String(), nullable=True),
    )
    # Partial-on-live uniqueness: an actor can be re-registered after
    # revoke (creates a new row); only one *live* row per actor.
    op.create_index(
        "uq_agent_actors_actor_live",
        "agent_actors",
        ["actor"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    # Hot path for `enforce_human_confirmation`: "is this actor live?"
    op.create_index(
        "ix_agent_actors_live",
        "agent_actors",
        ["actor"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    # Seed the corrected initial allowlist. `titan-archaedas` from the
    # #76 default is intentionally NOT seeded — it was never an actual
    # actor (the titan-archaedas project's agent uses X-Actor
    # `archaedas`). Seeded rows have `registered_by_actor = NULL` and
    # a description that points at the seeding migration.
    op.execute(
        sa.text(
            """
            INSERT INTO agent_actors (actor, description)
            VALUES
              ('titan-tyr', 'titan-tyr backend agent (writes from this repo); seeded from #78'),
              ('archaedas', 'titan-archaedas DevOps agent; seeded from #78'),
              ('mimiron', 'titan-mimiron UI agent; seeded from #78')
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_agent_actors_live", table_name="agent_actors")
    op.drop_index("uq_agent_actors_actor_live", table_name="agent_actors")
    op.drop_table("agent_actors")
