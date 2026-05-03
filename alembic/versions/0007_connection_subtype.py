"""connection contract subtype + connection_type discriminator + connection template

#32: add a third contract subtype, `connection`, for structural couplings
declared in build/config/deploy artifacts (no runtime data flow). Six
labels distinguish the kinds of structural binding (`builds-from`,
`instantiates`, `runs`, `member-of`, `depends-on`, `submodule`); these
live in a new `connection_type` column which is required iff
`subtype = 'connection'`. Per-label From/To Part subtype rules are
enforced in the contracts router (matches the binding precedent), not
here.

Schema changes in this revision:
- extend `ck_contracts_subtype_allowed` to admit 'connection'
  (drop+recreate per the 0006 ordering pattern)
- add nullable `connection_type` column on `contracts`
- add `ck_contracts_connection_type_required` (required iff connection)
- add `ck_contracts_connection_type_allowed` (enum guard)
- extend `ck_templates_kind_allowed` to admit 'connection'
- seed `connection` template at v1.0.0 active

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-03
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CONNECTION_TEMPLATE_V1 = """\
<!-- template: connection@<template-version> -->

# <connection-name>

**Connection type:** <builds-from | instantiates | runs | member-of | depends-on | submodule>
**Owner part:** <owner-name>
**Counterparty part:** <counterparty-name>

> **DELETE WHEN FILLING IN.** Everything in this blockquote is guidance
> for whoever fills the template; strip the entire block before POSTing.
>
> A Connection contract records a **structural binding** between two
> Parts where nothing flows at runtime. It captures couplings declared
> in Dockerfiles, compose files, Kubernetes manifests, or `.gitmodules`
> — not in running application code.
>
> If data flows between two Parts at runtime, that is an Interaction
> (env-agnostic) or a Binding (environment-specific runtime address) —
> use the matching template instead. Use Connection only for the
> static graph: "this image is built from this repo," "this container
> is a service in this stack," "this repo includes this other repo as
> a submodule."
>
> **Per-label From/To rules.** The `connection_type` discriminator
> picks one of six labels; each label has a fixed source-and-target
> Part subtype rule enforced at registration:
>
> | Label           | Owner part subtype  | Counterparty part subtype | What it records                                     |
> | --------------- | ------------------- | ------------------------- | --------------------------------------------------- |
> | `builds-from`   | software            | image                     | repository builds into image (Dockerfile + CI)      |
> | `instantiates`  | image               | container or pod          | image is run as a container or pod                  |
> | `runs`          | container or pod    | software                  | runtime hosts a specific software process            |
> | `member-of`     | container           | compose                   | container is a service entry in a compose stack     |
> | `depends-on`    | container           | container                 | startup ordering within a compose stack              |
> | `submodule`     | software            | software                  | one repository includes another via `.gitmodules`   |
>
> Labels referencing Part subtypes that are not yet implemented
> (`image`, `pod`, `compose`) reject at registration with a clear
> "not yet implemented" error. Today only `depends-on` (container ↔
> container) and `submodule` (software ↔ software) work end-to-end.
>
> Note: titan-tyr stores `owner_part`, `counterparty_part`, `subtype`,
> `connection_type`, and `version` separately on the API request —
> those JSON fields are canonical. The header above is for human
> readers; do not rely on it as machine-readable metadata.
>
> The HTML comment on the first line is a **template-version stamp**.
> Consuming skills (e.g. `/register-contract`) substitute
> `<template-version>` with the active template version they fetched.
> Drift-detection tooling reads it back to compare against the current
> active template. Do not remove the line; do not hand-edit the value.

## What this connection records

One to two sentences. What structural fact does this Connection
represent? Why are these two Parts coupled? What would break if this
binding were removed?

## Provider obligations

Binding commitments of the **counterparty** part (the one being
depended on):

- The version, tag, or SHA it is pinned at
- Stability or compatibility guarantees at build / config time

## Consumer obligations

Binding commitments of the **owner** part (the dependent):

- Keeping the pinned version current
- Notifying the counterparty before upgrading
- Any sequencing or compatibility requirements

## Pinned versions

| Component                                 | Pinned value |
| ----------------------------------------- | ------------ |
| <image tag / chart version / commit SHA>  | <value>      |

## Change protocol

Propose changes via `POST /contracts/{contract_id}/proposals` (or
`/propose-contract-change`). Tag the owner part owner and the
counterparty part owner for review. Version upgrades must be tested
before merging. Connection bodies move through the same propose /
accept / RC flow as interaction and binding contracts.

## Notes

Anything not captured above — known gaps, unresolved questions,
context worth preserving.
"""


def upgrade() -> None:
    bind = op.get_bind()

    # ---------- Phase 1: extend contract subtype allow-list ----------
    # Drop+recreate per the 0006 pattern. No data UPDATE needed (existing
    # rows are 'interaction' or 'binding', both still valid).
    op.execute(
        "ALTER TABLE contracts DROP CONSTRAINT ck_contracts_subtype_allowed"
    )
    op.create_check_constraint(
        "subtype_allowed",
        "contracts",
        "subtype IN ('interaction', 'binding', 'connection')",
    )

    # ---------- Phase 2: connection_type column + per-row CHECKs ----------
    op.add_column(
        "contracts",
        sa.Column("connection_type", sa.String(length=32), nullable=True),
    )
    op.create_check_constraint(
        "connection_type_required",
        "contracts",
        "(subtype = 'connection' AND connection_type IS NOT NULL) "
        "OR (subtype <> 'connection' AND connection_type IS NULL)",
    )
    op.create_check_constraint(
        "connection_type_allowed",
        "contracts",
        "connection_type IS NULL OR connection_type IN "
        "('builds-from', 'instantiates', 'runs', "
        "'member-of', 'depends-on', 'submodule')",
    )

    # ---------- Phase 3: extend templates kind allow-list ----------
    op.execute(
        "ALTER TABLE templates DROP CONSTRAINT ck_templates_kind_allowed"
    )
    op.create_check_constraint(
        "kind_allowed",
        "templates",
        "kind IN ('software', 'container', 'interaction', 'binding', 'connection')",
    )

    # ---------- Phase 4: seed the connection template at v1.0.0 active ----------
    bind.execute(sa.text("INSERT INTO templates (kind) VALUES ('connection')"))
    template_id = bind.execute(
        sa.text("SELECT id FROM templates WHERE kind = 'connection'")
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
        {"template_id": template_id, "markdown": CONNECTION_TEMPLATE_V1},
    )


def downgrade() -> None:
    bind = op.get_bind()

    # Strip the connection template (versions first, then row).
    bind.execute(
        sa.text(
            "DELETE FROM template_versions WHERE template_id IN "
            "(SELECT id FROM templates WHERE kind = 'connection')"
        )
    )
    bind.execute(sa.text("DELETE FROM templates WHERE kind = 'connection'"))

    # Restore 0006's templates kind allow-list (drop 'connection').
    op.execute(
        "ALTER TABLE templates DROP CONSTRAINT ck_templates_kind_allowed"
    )
    op.create_check_constraint(
        "kind_allowed",
        "templates",
        "kind IN ('software', 'container', 'interaction', 'binding')",
    )

    # Drop connection_type column + its two CHECKs (CHECKs first so the
    # column drop doesn't fight a constraint referencing it).
    # Use op.execute with the canonical (alembic-prefixed) name; passing
    # the full name to op.drop_constraint would re-prefix it (#32 lesson).
    op.execute(
        "ALTER TABLE contracts DROP CONSTRAINT ck_contracts_connection_type_allowed"
    )
    op.execute(
        "ALTER TABLE contracts DROP CONSTRAINT ck_contracts_connection_type_required"
    )
    op.drop_column("contracts", "connection_type")

    # Restore 0006's contract subtype allow-list (drop 'connection'). Any
    # connection-subtype rows would already 422 here because their column
    # was just dropped — but on a clean downgrade against a DB that has
    # such rows, the row-level CHECK below would fail. That's the correct
    # behaviour: you can't downgrade past a feature whose data is still
    # in use.
    op.execute(
        "ALTER TABLE contracts DROP CONSTRAINT ck_contracts_subtype_allowed"
    )
    op.create_check_constraint(
        "subtype_allowed",
        "contracts",
        "subtype IN ('interaction', 'binding')",
    )
