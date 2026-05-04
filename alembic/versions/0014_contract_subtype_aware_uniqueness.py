"""subtype-aware uniqueness on contracts (#42)

Widens the contracts uniqueness key from `(owner_part_id, counterparty_part_id)`
to `(owner_part_id, counterparty_part_id, subtype, connection_type)` with
PG-15 `NULLS NOT DISTINCT` semantics.

`connection_type` is `NULL` for `interaction` and `binding` rows and non-NULL
for `connection` rows. With `NULLS NOT DISTINCT`, the new key correctly
enforces:

  - one `interaction` per pair
  - one `binding`     per pair
  - one `connection`  per pair *per* `connection_type`

Without this, the multi-row Connections table that landed in `container@2.0.0`
(closed by #34) and `container@3.0.0` (templates audit) is unrealisable —
registering a `binding` on a pair that already holds a `connection`/`runs`
returns 409 even though both should coexist.

Pre-flight on the live db at the time of writing: 21 contracts, 21 unique
pairs, zero pairs with multiple rows. Migration is data-safe — no row
participates in either the dropped or added constraint as a collision.

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-04
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_contracts_owner_part_id_counterparty_part_id",
        "contracts",
        type_="unique",
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_contracts_subtype_pair "
        "ON contracts (owner_part_id, counterparty_part_id, subtype, connection_type) "
        "NULLS NOT DISTINCT"
    )


def downgrade() -> None:
    # Downgrade only succeeds when no pair holds more than one contract —
    # i.e. when no caller has yet relied on the widened key. Add a guard
    # so we fail fast with a clear message instead of corrupting on the
    # follow-up unique-constraint add.
    op.execute(
        "DO $$ "
        "BEGIN "
        "  IF EXISTS ( "
        "    SELECT 1 FROM contracts "
        "    GROUP BY owner_part_id, counterparty_part_id "
        "    HAVING COUNT(*) > 1 "
        "  ) THEN "
        "    RAISE EXCEPTION 'cannot downgrade 0014: rows exist that violate "
        "the narrower (owner_part_id, counterparty_part_id) uniqueness key'; "
        "  END IF; "
        "END $$;"
    )
    op.execute("DROP INDEX uq_contracts_subtype_pair")
    op.create_unique_constraint(
        "uq_contracts_owner_part_id_counterparty_part_id",
        "contracts",
        ["owner_part_id", "counterparty_part_id"],
    )
