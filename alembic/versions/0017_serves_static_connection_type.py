"""extend connection_type allow-list with 'serves-static' (#62)

Adds a seventh `connection_type` label, `serves-static`, capturing the
software-hosts-software static-asset case (e.g. nginx serving an SPA's
compiled bundle out of /usr/share/nginx/html). The router-side rule
table allows owner=software and counterparty=software for this label;
the DB CHECK only enforces the enum membership.

Revision ID: 0017
Revises: 0016
Create Date: 2026-05-04
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop+recreate both enum CHECKs with the new label appended.
    # No data UPDATE: existing rows already use one of the legacy six.
    # The proposal-table constraint must move in lockstep so a future
    # subtype-shift can propose connection_type='serves-static'
    # without tripping the proposal-row CHECK before it ever reaches
    # accept.
    op.execute(
        "ALTER TABLE contracts DROP CONSTRAINT ck_contracts_connection_type_allowed"
    )
    op.create_check_constraint(
        "connection_type_allowed",
        "contracts",
        "connection_type IS NULL OR connection_type IN "
        "('builds-from', 'instantiates', 'runs', "
        "'member-of', 'depends-on', 'submodule', 'serves-static')",
    )

    # 0011 created this constraint via `sa.CheckConstraint(name=...)`
    # inside `op.create_table`. The metadata naming convention then
    # re-prefixed the literal name, producing an 84-char identifier;
    # SQLAlchemy auto-truncates such names with a 4-char deterministic
    # hash suffix (`ck_contract_subtype_proposals_ck_contract_subtype_propo_<hex4>`).
    # Look up the real name by definition so we don't have to guess
    # the hash; the IN-list check on `new_connection_type` is the
    # only constraint matching this pattern.
    bind = op.get_bind()
    name_row = bind.execute(
        sa.text(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = 'contract_subtype_proposals'::regclass "
            "  AND contype = 'c' "
            "  AND pg_get_constraintdef(oid) LIKE "
            "      '%new_connection_type%builds-from%submodule%'"
        )
    ).scalar_one()
    op.execute(
        f'ALTER TABLE contract_subtype_proposals DROP CONSTRAINT "{name_row}"'
    )
    op.create_check_constraint(
        "connection_type_allowed",
        "contract_subtype_proposals",
        "new_connection_type IS NULL OR new_connection_type IN "
        "('builds-from', 'instantiates', 'runs', "
        "'member-of', 'depends-on', 'submodule', 'serves-static')",
    )


def downgrade() -> None:
    # Upgrade left this table's constraint at the single-prefix
    # alembic-conventional name, so drop *that* (not the doubled
    # name 0011 originally created).
    op.execute(
        "ALTER TABLE contract_subtype_proposals "
        "DROP CONSTRAINT ck_contract_subtype_proposals_connection_type_allowed"
    )
    op.create_check_constraint(
        "connection_type_allowed",
        "contract_subtype_proposals",
        "new_connection_type IS NULL OR new_connection_type IN "
        "('builds-from', 'instantiates', 'runs', "
        "'member-of', 'depends-on', 'submodule')",
    )

    op.execute(
        "ALTER TABLE contracts DROP CONSTRAINT ck_contracts_connection_type_allowed"
    )
    op.create_check_constraint(
        "connection_type_allowed",
        "contracts",
        "connection_type IS NULL OR connection_type IN "
        "('builds-from', 'instantiates', 'runs', "
        "'member-of', 'depends-on', 'submodule')",
    )
