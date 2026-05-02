"""templates: tables + seed v1.0.0

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-02
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SOFTWARE_TEMPLATE_V1 = """\
# <software-name>

**Owner:** <team or person>
**Repository:** <repo-uri>

> A Software node is a unit of software ownership — one codebase, one
> deployable boundary, one owning team. It describes *what* the
> software does and *what* it exposes or consumes at its boundary, not
> where it runs.
>
> Note: titan-tyr stores `name`, `repo_uri`, and `version` separately
> on the API request — the values you supply in the JSON body are
> canonical. Owner / Repository above are for human readers; do not
> rely on them as machine-readable metadata.

## Purpose

Two to four sentences. What does this software do and why does it
exist? Written for a reader with no prior context.

## Ports

A Port is a **logical operation** at the repository boundary — not a
single HTTP method. One Port covers all the routes/methods that
together implement the same operation. For example, "manage software
records" is one Port (covering `POST /software`, `GET /software/{name}`,
`PUT /software/{name}`), not three.

Each Port references an interface contract registered with titan-tyr
(`POST /contracts`). A single Port may have multiple counterparties:
list them all (comma-separated, or one row per counterparty — your
call, but be consistent within this software's contract).

| Port | Direction | Counterparty software |
| ---- | --------- | --------------------- |
| <port-name> | <in \\| out> | <counterparty-name>[, <counterparty-name>...] |

### What is *not* a Port

- **Datastore access** (your own DB, cache, files on disk). This is
  internal implementation detail. Only model interfaces with
  *registered software* as ports. If a datastore matters to the
  contract, describe it in Notes.
- **Cross-cutting concerns** like auth middleware, logging, metrics
  emission. Mention in Notes if relevant.

### Direction conventions

Direction is from *this* software's perspective:

| Pattern                                                       | Direction      |
| ------------------------------------------------------------- | -------------- |
| Receives a request (HTTP endpoint, RPC handler, CLI command)  | `in`           |
| Makes an outbound request and ignores the response            | `out`          |
| Makes an outbound request and uses the response               | `out` and `in` |
| Subscribes to a queue, topic, or event stream                 | `in`           |
| Publishes to a queue, topic, or event stream                  | `out`          |

REST-specific cases follow the same rule. A `GET` you serve is `in`
because data flows into the request handler; a `GET` you make is `in`
because the response data flows back into your code. A `POST` you
serve is `in`; a `POST` you make and care about the response is
`out` + `in`; a `POST` you make and ignore the response is `out` only.

## Notes

Anything not captured above — unresolved questions, known gaps,
context worth recording at the software level.
"""


CONTRACT_TEMPLATE_V1 = """\
# <interface-name>

**Protocol:** <REST | Kafka | gRPC | GraphQL | JDBC | Webhook | Custom>
**Owner software:** <owner-name> port <port-name>
**Counterparty software:** <counterparty-name> port <port-name>

> An interface contract carries data between two Software nodes. It is
> the binding agreement on what is exchanged — protocol, schema, error
> handling. Environment-agnostic: no hostnames, no listening ports, no
> addresses.
>
> Note: titan-tyr stores `owner_software`, `counterparty_software`, and
> `version` separately on the API request — those JSON fields are
> canonical. The header above is for human readers; do not rely on it
> as machine-readable metadata.

## What this interface carries

One to two sentences. What data flows here, and what business or
technical purpose does the exchange serve?

## Provider obligations

Binding commitments of the **owner** software. Each item is a
commitment, not a description.

- ...

## Consumer obligations

Binding commitments of the **counterparty** software.

- ...

## Schema

What this section contains depends on the protocol:

| Protocol  | Schema should contain                                                              |
| --------- | ---------------------------------------------------------------------------------- |
| REST      | Path, HTTP method, request fields, response fields, status codes                   |
| Kafka     | Topic, message fields, partition key, delivery guarantee, consumer group           |
| gRPC      | Service, method, request message fields, response message fields                   |
| GraphQL   | Operation name, query / mutation fields, response fields                           |
| JDBC      | Schema, table or view, access type, connection constraints                         |
| Webhook   | Endpoint path, payload fields, signature verification, retry expectations          |

### Request / message

| Field   | Type   | Required | Description     |
| ------- | ------ | -------- | --------------- |
| <field> | <type> | <yes/no> | <description>   |

### Response (if applicable)

| Field   | Type   | Required | Description     |
| ------- | ------ | -------- | --------------- |
| <field> | <type> | <yes/no> | <description>   |

### Errors (if applicable)

| Code / condition | Meaning   | Consumer action          |
| ---------------- | --------- | ------------------------ |
| <code>           | <meaning> | <retry / fail / ignore>  |

## Change protocol

Propose a change by registering a new proposal:

```
POST /contracts/{contract_id}/proposals
{ "version": "1.X.0-rcN", "markdown": "..." }
```

Iterate on `-rcN` versions until both sides agree, then propose the
stable `1.X.0`. The **owner software** accepts the proposal:

```
POST /contracts/{contract_id}/proposals/{version}/accept
```

Acceptance flips the status to `active` and (for RCs) creates a new
stable active version. All RCs and superseded proposals are preserved
in titan-tyr for posterity.

Breaking changes (`MAJOR` bump) need an explicit migration window —
record it in the proposal's markdown so accepting the proposal locks
in the cutover plan.

## Notes

Anything not captured above — known gaps, unresolved questions,
context worth preserving.
"""


def upgrade() -> None:
    op.create_table(
        "templates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("kind", name="uq_templates_kind"),
        sa.CheckConstraint(
            "kind IN ('software', 'contract')", name="ck_templates_kind_allowed"
        ),
    )

    op.create_table(
        "template_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_major", sa.Integer(), nullable=False),
        sa.Column("version_minor", sa.Integer(), nullable=False),
        sa.Column("version_patch", sa.Integer(), nullable=False),
        sa.Column("prerelease", sa.String(), nullable=True),
        sa.Column("markdown", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("promoted_from_prerelease", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["templates.id"],
            ondelete="CASCADE",
            name="fk_template_versions_template_id_templates",
        ),
        sa.CheckConstraint("version_major >= 0", name="ck_template_versions_version_major_nonneg"),
        sa.CheckConstraint("version_minor >= 0", name="ck_template_versions_version_minor_nonneg"),
        sa.CheckConstraint("version_patch >= 0", name="ck_template_versions_version_patch_nonneg"),
        sa.CheckConstraint(
            "status IN ('active', 'proposal')", name="ck_template_versions_status_allowed"
        ),
        sa.CheckConstraint(
            "prerelease IS NULL OR prerelease ~ '^rc[0-9]+$'",
            name="ck_template_versions_prerelease_grammar",
        ),
        sa.CheckConstraint(
            "status = 'proposal' OR prerelease IS NULL",
            name="ck_template_versions_active_must_be_stable",
        ),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_template_versions_template_id_version_prerelease "
        "ON template_versions (template_id, version_major, version_minor, version_patch, prerelease) "
        "NULLS NOT DISTINCT"
    )
    op.execute(
        "CREATE INDEX ix_template_versions_template_id_version "
        "ON template_versions "
        "(template_id, version_major DESC, version_minor DESC, version_patch DESC, prerelease DESC NULLS FIRST)"
    )
    op.execute(
        "CREATE INDEX ix_template_versions_template_id_status "
        "ON template_versions (template_id, status)"
    )

    # Seed the two templates at v1.0.0 active.
    bind = op.get_bind()
    for kind, markdown in (
        ("software", SOFTWARE_TEMPLATE_V1),
        ("contract", CONTRACT_TEMPLATE_V1),
    ):
        bind.execute(
            sa.text(
                "INSERT INTO templates (kind) VALUES (:kind) RETURNING id"
            ),
            {"kind": kind},
        )
        # Re-fetch the inserted id (RETURNING in raw SQL is portable but the
        # cursor-vs-result handling differs across drivers; a SELECT is simpler).
        template_id = bind.execute(
            sa.text("SELECT id FROM templates WHERE kind = :kind"),
            {"kind": kind},
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
            {"template_id": template_id, "markdown": markdown},
        )


def downgrade() -> None:
    op.drop_table("template_versions")
    op.drop_table("templates")
