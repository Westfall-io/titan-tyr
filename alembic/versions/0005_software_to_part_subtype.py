"""rename software → part, add subtype, seed container template

Phases 1+2+3 of #23 in a single migration:
- rename software / software_versions tables and FK columns
- rename explicitly-named indexes/constraints to match
- add `subtype` column on parts (default 'software' for backfill, then
  drop the default — new INSERTs must specify it explicitly per #23)
- extend templates.kind allow-list to include 'container'
- seed the container template at v1.0.0 active

Constraint/index names follow the project's MetaData naming convention
(see src/db.py NAMING_CONVENTION): pk_<table>, uq_<table>_<col>,
fk_<table>_<col>_<referred_table>, ix_<table>_<cols>,
ck_<table>_<name>. Migration 0001/0002 pass already-prefixed names
through `op.create_table`, so the convention applies twice and the
actual stored name is `ck_<table>_ck_<table>_<name>`. We use those
real names below where they apply.

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-03
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CONTAINER_TEMPLATE_V1 = """\
<!-- template: container@<template-version> -->

# <container-name>

**Type:** Container
**Version:** <semver>
**Owner:** <team or person>
**Runs image:** <image-name (free-form for now; Image as a Part subtype is deferred)>
**Git SHA:** <git sha at deploy; populated manually until backend automation lands>
**Last modified:** <iso timestamp; populated manually until backend automation lands>

> A Container Part is a running instance of an Image Part in a Docker
> runtime. It is the live, executing form of the software at a
> specific address on a specific network.
>
> A Container Part has two distinct relationships with the Software
> Part it runs:
> 1. A **Connection** (`runs`) — the structural fact that this
>    container hosts this software process. Nothing flows.
> 2. A **Binding Interface** — address information (host, port) flows
>    from the Container Part outward to the Software Part so the
>    software knows where it is reachable on the network.
>
> **DELETE WHEN FILLING IN.**

## Purpose

One to two sentences. What does this container do in the context of
the system it belongs to?

## Ports

A Container Part has paired `in` and `out` Ports for each opened
network port:

- **`in`** — traffic arrives from outside the container on this port.
  References the same Interaction Interface as the corresponding
  Software Part Port.
- **`out`** — traffic passes through to the software process inside.
  The Binding Interface flows outward from this Port to the Software
  Part's corresponding `in` Port. References both the Interaction
  Interface and the Binding Interface.

| Port    | Direction | Resolved address    | Interface                          | Notes               |
| ------- | --------- | ------------------- | ---------------------------------- | ------------------- |
| <name>  | in        | <host:port>         | <interaction interface name>       | traffic enters      |
| <name>  | out       | <internal address>  | <interaction + binding interface>  | binding to software |

## Connections

| Connected to     | Connection type | Contract       |
| ---------------- | --------------- | -------------- |
| <software-name>  | runs            | <contract id>  |

> **DELETE WHEN FILLING IN.** The `instantiates` (Image) and
> `member-of` (Compose) connection types are part of the SysMLv2
> Container definition but the Image and Compose Part subtypes are
> deferred. Leave those rows out for now; add them when those
> subtypes land.

## Feedback

Anything not captured above.
"""


def upgrade() -> None:
    # ---------- Phase 1: rename tables ----------
    op.rename_table("software", "parts")
    op.rename_table("software_versions", "part_versions")

    # PK / UQ constraints — renaming the constraint auto-renames its
    # backing index in PG, so we don't need parallel ALTER INDEX calls.
    op.execute(
        "ALTER TABLE parts RENAME CONSTRAINT pk_software TO pk_parts"
    )
    op.execute(
        "ALTER TABLE parts RENAME CONSTRAINT uq_software_name TO uq_parts_name"
    )
    op.execute(
        "ALTER TABLE part_versions "
        "RENAME CONSTRAINT pk_software_versions TO pk_part_versions"
    )

    # ---------- Phase 1: rename FK column on part_versions ----------
    op.alter_column("part_versions", "software_id", new_column_name="part_id")

    op.execute(
        "ALTER TABLE part_versions "
        "RENAME CONSTRAINT fk_software_versions_software_id_software "
        "TO fk_part_versions_part_id_parts"
    )
    op.execute(
        "ALTER TABLE part_versions "
        "RENAME CONSTRAINT uq_software_versions_version "
        "TO uq_part_versions_version"
    )
    # ix_ indexes are pure indexes (no parallel constraint), so ALTER INDEX.
    op.execute(
        "ALTER INDEX ix_software_versions_software_id_version "
        "RENAME TO ix_part_versions_part_id_version"
    )

    # ---------- Phase 1: rename FK columns on contracts ----------
    op.alter_column(
        "contracts", "owner_software_id", new_column_name="owner_part_id"
    )
    op.alter_column(
        "contracts",
        "counterparty_software_id",
        new_column_name="counterparty_part_id",
    )

    op.execute(
        "ALTER TABLE contracts "
        "RENAME CONSTRAINT fk_contracts_owner_software_id_software "
        "TO fk_contracts_owner_part_id_parts"
    )
    op.execute(
        "ALTER TABLE contracts "
        "RENAME CONSTRAINT fk_contracts_counterparty_software_id_software "
        "TO fk_contracts_counterparty_part_id_parts"
    )
    op.execute(
        "ALTER TABLE contracts "
        "RENAME CONSTRAINT uq_contracts_owner_software_id_counterparty_software_id "
        "TO uq_contracts_owner_part_id_counterparty_part_id"
    )

    # ---------- Phase 2: add subtype column ----------
    op.add_column(
        "parts",
        sa.Column(
            "subtype",
            sa.String(),
            nullable=False,
            server_default="software",  # backfill existing rows
        ),
    )
    # Drop the server default — new INSERTs must specify subtype explicitly
    # (the API will require it; per direction #1 this is a breaking change).
    op.alter_column("parts", "subtype", server_default=None)

    op.create_check_constraint(
        "subtype_allowed",
        "parts",
        "subtype IN ('software', 'container')",
    )

    # ---------- Phase 2/3: extend templates allow-list + seed container ----------
    # Note: 0001/0002 created the constraint via raw `name="ck_templates_kind_allowed"`,
    # which the alembic naming-convention double-prefixed to
    # ck_templates_ck_templates_kind_allowed. Drop by that real name, recreate
    # with a clean unprefixed name (alembic will single-prefix it).
    op.execute(
        "ALTER TABLE templates DROP CONSTRAINT ck_templates_ck_templates_kind_allowed"
    )
    op.create_check_constraint(
        "kind_allowed",
        "templates",
        "kind IN ('software', 'contract', 'container')",
    )

    bind = op.get_bind()
    bind.execute(sa.text("INSERT INTO templates (kind) VALUES ('container')"))
    template_id = bind.execute(
        sa.text("SELECT id FROM templates WHERE kind = 'container'")
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
        {"template_id": template_id, "markdown": CONTAINER_TEMPLATE_V1},
    )


def downgrade() -> None:
    # Strip the container template
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM template_versions WHERE template_id IN "
            "(SELECT id FROM templates WHERE kind = 'container')"
        )
    )
    bind.execute(sa.text("DELETE FROM templates WHERE kind = 'container'"))

    # Restore the templates kind constraint to the original double-prefixed name.
    op.execute(
        "ALTER TABLE templates DROP CONSTRAINT ck_templates_kind_allowed"
    )
    op.execute(
        "ALTER TABLE templates ADD CONSTRAINT ck_templates_ck_templates_kind_allowed "
        "CHECK (kind IN ('software', 'contract'))"
    )

    # Drop subtype column
    op.drop_constraint("subtype_allowed", "parts", type_="check")
    op.drop_column("parts", "subtype")

    # Reverse the constraint renames on contracts
    op.execute(
        "ALTER TABLE contracts "
        "RENAME CONSTRAINT uq_contracts_owner_part_id_counterparty_part_id "
        "TO uq_contracts_owner_software_id_counterparty_software_id"
    )
    op.execute(
        "ALTER TABLE contracts "
        "RENAME CONSTRAINT fk_contracts_counterparty_part_id_parts "
        "TO fk_contracts_counterparty_software_id_software"
    )
    op.execute(
        "ALTER TABLE contracts "
        "RENAME CONSTRAINT fk_contracts_owner_part_id_parts "
        "TO fk_contracts_owner_software_id_software"
    )
    op.alter_column(
        "contracts",
        "counterparty_part_id",
        new_column_name="counterparty_software_id",
    )
    op.alter_column(
        "contracts", "owner_part_id", new_column_name="owner_software_id"
    )

    # Reverse the part_versions renames
    op.execute(
        "ALTER INDEX ix_part_versions_part_id_version "
        "RENAME TO ix_software_versions_software_id_version"
    )
    op.execute(
        "ALTER TABLE part_versions "
        "RENAME CONSTRAINT uq_part_versions_version "
        "TO uq_software_versions_version"
    )
    op.execute(
        "ALTER TABLE part_versions "
        "RENAME CONSTRAINT fk_part_versions_part_id_parts "
        "TO fk_software_versions_software_id_software"
    )
    op.alter_column("part_versions", "part_id", new_column_name="software_id")

    # Reverse the table renames + PK / unique constraint names
    op.execute(
        "ALTER TABLE part_versions "
        "RENAME CONSTRAINT pk_part_versions TO pk_software_versions"
    )
    op.execute(
        "ALTER TABLE parts RENAME CONSTRAINT uq_parts_name TO uq_software_name"
    )
    op.execute(
        "ALTER TABLE parts RENAME CONSTRAINT pk_parts TO pk_software"
    )
    op.rename_table("part_versions", "software_versions")
    op.rename_table("parts", "software")
