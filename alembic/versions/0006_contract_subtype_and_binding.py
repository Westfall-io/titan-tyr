"""contract subtype + binding template + contract→interaction kind rename

Phase 1+2 of #24 in a single migration:
- add `subtype` column on contracts (default 'interaction' for backfill,
  then drop the default — new INSERTs must specify it explicitly per #24)
- rename templates row kind 'contract' → 'interaction' (template_versions
  rows ride along by template_id, no FK churn)
- extend templates.kind allow-list to drop 'contract' and add
  ('interaction', 'binding')
- seed the binding template at v1.0.0 active

Per direction in the issue thread: defer pod subtype entirely. Binding
source/target subtype enforcement (container → software) happens in the
router layer, not in the schema — keeps the constraint legible and the
error messages user-friendly.

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-02
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


BINDING_TEMPLATE_V1 = """\
<!-- template: binding@<template-version> -->

# <binding-interface-name>

**Type:** Binding
**Version:** <semver>
**Environment:** <local | staging | production | ...>
**Owner:** <team responsible for this deployment binding>
**From:** <Container Part name> port <Port name>
**To:** <Software Part name> port <Port name>
**Interaction Interface:** <Interaction contract name and version>
**Git SHA:** <git sha at deploy; populated manually until backend automation lands>
**Last modified:** <iso timestamp; populated manually until backend automation lands>

> A Binding contract carries address components (protocol, host, port)
> from a Container Part outward to a Software Part, so the software
> can construct its own callable address per environment.
>
> A Binding is **environment-specific**. The same Software Part will
> have different Binding values in local development, staging, and
> production — each carried by a separate Container Part (e.g.
> `payments-prod` vs `payments-staging`) and so a separate binding
> contract.
>
> A Binding always references the Interaction contract it resolves —
> protocol/path come from the Interaction; host/port from this
> Binding.
>
> **DELETE WHEN FILLING IN.**

## What This Interface Carries

One sentence. Which deployment address does this binding resolve and
in which environment?

## Provider Obligations

What the Container Part commits to:
- The host it is reachable at
- The port it opens
- The protocol it accepts

## Consumer Obligations

What the Software Part commits to:
- The environment variable or config key it reads
- How it constructs the full address from these components

## Binding Components

| Component | Value                       | Carried via                          |
| --------- | --------------------------- | ------------------------------------ |
| protocol  | <e.g. http>                 | <hardcoded or env var name>          |
| host      | <e.g. payments-container>   | <env var name>                       |
| port      | <e.g. 8080>                 | <env var name>                       |
| base path | <e.g. /api/v1>              | defined in Interaction contract      |

## Resolved Address

The complete base URL this binding produces, e.g.
`http://payments-container:8080/api/v1`.

## Change Protocol

Propose changes via `POST /contracts/{contract_id}/proposals` (or
`/propose-contract-change`). Tag the Container Part owner and the
Software Part owner for review. Host or port changes in a live
environment are breaking and require coordinated deployment — surface
the rollout plan in the proposal body.

## Open Proposals

No open proposals.

## Feedback

Anything not captured above.
"""


def upgrade() -> None:
    # ---------- Phase 1: add subtype column on contracts ----------
    op.add_column(
        "contracts",
        sa.Column(
            "subtype",
            sa.String(),
            nullable=False,
            server_default="interaction",  # backfill existing rows
        ),
    )
    # Drop the server default — new INSERTs must specify subtype explicitly.
    op.alter_column("contracts", "subtype", server_default=None)

    op.create_check_constraint(
        "subtype_allowed",
        "contracts",
        "subtype IN ('interaction', 'binding')",
    )

    # ---------- Phase 2: replace kind allow-list ----------
    # Drop FIRST so the UPDATE below can rename 'contract' → 'interaction'
    # without violating the old CHECK (which knows nothing about
    # 'interaction'). 0005 left this as the unprefixed
    # `ck_templates_kind_allowed` (single-prefixed by alembic to that exact
    # name).
    op.execute(
        "ALTER TABLE templates DROP CONSTRAINT ck_templates_kind_allowed"
    )

    # template_versions rows are joined via template_id, so the rename is
    # a single UPDATE on the templates row — no FK churn.
    bind = op.get_bind()
    bind.execute(
        sa.text("UPDATE templates SET kind = 'interaction' WHERE kind = 'contract'")
    )

    op.create_check_constraint(
        "kind_allowed",
        "templates",
        "kind IN ('software', 'container', 'interaction', 'binding')",
    )

    # ---------- Phase 2: seed the binding template at v1.0.0 active ----------
    bind.execute(sa.text("INSERT INTO templates (kind) VALUES ('binding')"))
    template_id = bind.execute(
        sa.text("SELECT id FROM templates WHERE kind = 'binding'")
    ).scalar_one()
    bind.execute(
        sa.text(
            """
            INSERT INTO template_versions
              (template_id, version_major, version_minor, version_patch,
               prerelease, markdown, status, accepted_at)
            VALUES
              (:template_id, 1, 0, 0, NULL, :markdown, 'active', now())
            """
        ),
        {"template_id": template_id, "markdown": BINDING_TEMPLATE_V1},
    )


def downgrade() -> None:
    bind = op.get_bind()

    # Strip the binding template
    bind.execute(
        sa.text(
            "DELETE FROM template_versions WHERE template_id IN "
            "(SELECT id FROM templates WHERE kind = 'binding')"
        )
    )
    bind.execute(sa.text("DELETE FROM templates WHERE kind = 'binding'"))

    # Drop CHECK first so the UPDATE below can rename 'interaction' → 'contract'
    # without violating the new CHECK (which doesn't know about 'contract').
    op.execute(
        "ALTER TABLE templates DROP CONSTRAINT ck_templates_kind_allowed"
    )

    # Rename templates kind 'interaction' → 'contract'
    bind.execute(
        sa.text("UPDATE templates SET kind = 'contract' WHERE kind = 'interaction'")
    )

    # Restore the 0005 allow-list (software, contract, container).
    op.create_check_constraint(
        "kind_allowed",
        "templates",
        "kind IN ('software', 'contract', 'container')",
    )

    # Drop subtype column on contracts
    op.drop_constraint("subtype_allowed", "contracts", type_="check")
    op.drop_column("contracts", "subtype")
