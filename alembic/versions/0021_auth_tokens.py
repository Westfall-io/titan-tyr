"""per-caller auth tokens with scopes (#81 + #82 + #84)

Replaces the single hardcoded shared bearer (`sysmlv2` in
`src/auth.py`) with per-caller tokens stored hashed at rest, each
carrying an actor identity + scope set.

The auth dependency on the API side becomes "look up the bearer's
sha256 in this table, derive X-Actor and scopes from the row." The
header-asserted X-Actor is no longer load-bearing once a per-caller
token is in use — it's overridden by the token's claim.

Stage 1 (this migration + companion code):
- New table `auth_tokens` with hash, actor, scopes, soft-delete.
- The legacy shared bearer is preserved alongside, but its source
  moves from a hardcoded constant to an env var
  (`TITAN_TYR_BEARER_PASSWORD`) defaulting to empty (fail-closed).
  Consumers can rotate to per-caller tokens at their own pace.

Stage 2 (future PR): drop the legacy shared-bearer path entirely.

No rows are seeded — the operator runs a CLI
(`python -m src.cli issue-token`) once at first deploy to mint an
admin token, then issues all subsequent tokens via
`POST /auth-tokens` over the API. Seeding plaintexts in the
migration would risk them ending up in commits or logs.

Hash is sha256 (not bcrypt/argon2). These are 32-byte server-issued
random tokens, not human-chosen passwords; the slow-by-design
property of password-grade KDFs buys little here while adding a
per-request cost.

Revision ID: 0021
Revises: 0020
Create Date: 2026-05-05
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "auth_tokens",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # sha256 hex digest (64 chars). Stored hashed so a database
        # leak doesn't surrender working tokens.
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        # Visible-in-list prefix for ops ("which token is this?"). The
        # first 8 chars of the plaintext token; non-secret. Useful
        # for revocation grep without exposing the token itself.
        sa.Column("token_prefix", sa.String(length=8), nullable=False),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        # Scope set as a sorted text[]. Closed enum at the schema
        # layer (read | write | revoke-agent); ARRAY chosen over a
        # bitmask so future scopes don't need a migration.
        sa.Column(
            "scopes",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("issued_by_actor", sa.String(), nullable=True),
        # Optional expiry. Long-lived agent tokens get NULL; short-
        # lived human ops tokens can carry a date.
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        # Updated opportunistically by the auth dependency. Not on a
        # write path that blocks the request — best-effort.
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        # Soft-delete via revoke (matching agent-actors pattern in #78).
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_actor", sa.String(), nullable=True),
        sa.Column("revoke_rationale", sa.String(), nullable=True),
    )
    # Hot-path lookup: "given this bearer hash, find the live token row."
    # Partial-on-live so a revoked token's hash can never satisfy the
    # auth check, even via index scan.
    op.create_index(
        "uq_auth_tokens_hash_live",
        "auth_tokens",
        ["token_hash"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    # Convenience: filter live tokens by actor (for ops sweeps).
    op.create_index(
        "ix_auth_tokens_actor_live",
        "auth_tokens",
        ["actor"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_auth_tokens_actor_live", table_name="auth_tokens")
    op.drop_index("uq_auth_tokens_hash_live", table_name="auth_tokens")
    op.drop_table("auth_tokens")
