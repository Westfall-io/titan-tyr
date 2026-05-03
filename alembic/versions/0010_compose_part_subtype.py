"""compose part subtype + compose template

#37: add the `compose` Part subtype, representing a Docker Compose
stack — a collection of services declared in a `docker-compose.yml`
(or `compose.yaml`) file, typically run together in local dev or
staging. Unblocks the last remaining `connection_type` label deferred
from #32:

- `member-of`: Container → Compose (a container is a service entry in
  a compose stack)

A Compose Part is metadata *about* the stack file — the file itself
remains the source of truth. The Part body records file path, services
list, network topology, volume mounts, and env-var overlay strategy.

After this migration every `connection_type` label has both arms
implemented; the router's deferred-subtype guard is a no-op for the
current rule set, but stays in place for future rules.

Schema changes in this revision:
- extend `ck_parts_subtype_allowed` from {software, container, image,
  pod} to {software, container, image, pod, compose} (drop+recreate
  per the 0006 ordering pattern; no data UPDATE — existing rows stay
  valid)
- extend `ck_templates_kind_allowed` to admit 'compose' (drop+recreate)
- seed `compose` template at v1.0.0 active

The router-side `_PART_SUBTYPES_IMPLEMENTED` allow-set in
`src/routers/contracts.py` also extends to include `compose`, which
is what actually unblocks the `member-of` label end-to-end. The
schema CHECK is the persistence guard; the router check is the
validation layer.

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-03
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


COMPOSE_TEMPLATE_V1 = """\
<!-- template: compose@<template-version> -->

# <stack-name>

**Type:** Compose
**Owner:** <team or person>
**File path:** <repo-relative path to compose.yaml, e.g. docker/compose.yaml>
**COMPOSE_PROJECT_NAME:** <project name override, if used>

> **DELETE WHEN FILLING IN.** Everything in this blockquote is guidance
> for whoever fills the template; strip the entire block before POSTing.
>
> A Compose Part represents a **Docker Compose stack** — a collection
> of services declared in a single compose file, typically run
> together in local development or a small shared staging env.
> The Compose Part is metadata *about* the stack file; the file
> itself remains the source of truth (this Part should never drift
> into hand-curated content that contradicts the file).
>
> One Compose Part has many `member-of` inbound edges from its
> Container Parts (one per service). It does **not** have outbound
> connections of its own — the stack is a bag of services, not a
> service itself. If you want to record host bindings or external
> dependencies, those live on the individual Container Parts.
>
> A Compose Part participates in one `connection_type` label:
> - `member-of` (Container → Compose): a container is a service
>   entry in this compose stack. One row per service in the stack.
>
> Note: titan-tyr stores `name`, `repo_uri`, `issue_tracker_uri`,
> `aliases`, `subtype`, and `version` separately on the API request —
> those JSON fields are canonical. The header above is for human
> readers; do not rely on it as machine-readable metadata.
>
> `name` must be a **slug**: lowercase letters, digits, and hyphens
> (1–64 chars, no leading/trailing hyphen). Naming convention:
> mirror `COMPOSE_PROJECT_NAME` if set, otherwise the directory name
> compose runs under. For typical setups: `<repo>-stack` (e.g.
> `watchervault-stack`, `payments-stack`). For a single repo with
> multiple stacks, suffix the role: `payments-stack-dev`,
> `payments-stack-integration`.
>
> `repo_uri` should point at the repo that owns the compose file —
> the file path field above is repo-relative.
>
> The HTML comment on the first line is a **template-version stamp**.
> Consuming skills (e.g. `/register-part`) substitute
> `<template-version>` with the active template version they fetched.
> Drift-detection tooling reads it back to compare against the
> current active template. Do not remove the line; do not hand-edit
> the value.

## Purpose

Two to four sentences. What does this stack run together, and why is
it bundled? Local dev convenience? Integration test env? Cover the
trigger pattern (developer runs `docker compose up`? CI runs it
in a job? always-on staging?), and any non-obvious composition
choices (vendored services, mock backends, profiles).

## Services

The services declared in the compose file. One row per service. The
`member-of` Connection contract for each pair is the canonical
wiring; this table is for human readers.

| Service name      | Container part         | Image / build context              | Notes                                   |
| ----------------- | ---------------------- | ---------------------------------- | --------------------------------------- |
| <compose-svc>     | <container-part-name>  | <image:tag or build context path>  | <e.g. "depends_on healthcheck">         |

## Network topology

How services in this stack reach each other. Cover:

- **Default network:** the bridge network compose creates (typically
  `<project>_default`). DNS resolution by service name.
- **Custom networks:** any additional networks declared and which
  services join them.
- **External networks:** networks defined elsewhere this stack
  attaches to (shared infra, ingress, etc).
- **Host port exposures:** which services publish ports to the host
  and on what mapping. Note conflicts to watch for in dev
  environments.

## Volume mounts

Volumes declared in the stack. Cover:

- **Named volumes:** persistent storage created by compose; what
  service uses it for and what data lives there.
- **Bind mounts:** host paths mounted into containers (live code
  reload, config files, fixtures).
- **External volumes:** volumes defined elsewhere this stack
  attaches to.

## Env-var overlay strategy

How environment variables flow into services in this stack:

- **`.env` files:** which `.env` / `*.env` files compose loads, and
  the precedence order.
- **Per-service `environment` blocks:** notable defaults set in the
  compose file itself.
- **Required overrides:** vars the developer must export before
  `compose up` (API keys, secrets, machine-specific paths).
- **Profiles:** any compose profiles that gate optional services
  (e.g. `--profile=monitoring`).

## Notes

Anything not captured above — depends_on healthcheck setup, restart
policy quirks, build cache strategies, known issues running on
specific OSes (Apple Silicon, WSL2), upgrade path between compose
v1 and v2 syntax.
"""


def upgrade() -> None:
    bind = op.get_bind()

    # ---------- Phase 1: extend parts.subtype allow-list ----------
    op.execute(
        "ALTER TABLE parts DROP CONSTRAINT ck_parts_subtype_allowed"
    )
    op.create_check_constraint(
        "subtype_allowed",
        "parts",
        "subtype IN ('software', 'container', 'image', 'pod', 'compose')",
    )

    # ---------- Phase 2: extend templates.kind allow-list ----------
    op.execute(
        "ALTER TABLE templates DROP CONSTRAINT ck_templates_kind_allowed"
    )
    op.create_check_constraint(
        "kind_allowed",
        "templates",
        "kind IN ('software', 'container', 'image', 'pod', 'compose', "
        "'interaction', 'binding', 'connection')",
    )

    # ---------- Phase 3: seed the compose template at v1.0.0 active ----
    bind.execute(sa.text("INSERT INTO templates (kind) VALUES ('compose')"))
    template_id = bind.execute(
        sa.text("SELECT id FROM templates WHERE kind = 'compose'")
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
        {"template_id": template_id, "markdown": COMPOSE_TEMPLATE_V1},
    )


def downgrade() -> None:
    bind = op.get_bind()

    # Strip the compose template (versions first, then row).
    bind.execute(
        sa.text(
            "DELETE FROM template_versions WHERE template_id IN "
            "(SELECT id FROM templates WHERE kind = 'compose')"
        )
    )
    bind.execute(sa.text("DELETE FROM templates WHERE kind = 'compose'"))

    # Restore 0009's templates kind allow-list (drop 'compose').
    op.execute(
        "ALTER TABLE templates DROP CONSTRAINT ck_templates_kind_allowed"
    )
    op.create_check_constraint(
        "kind_allowed",
        "templates",
        "kind IN ('software', 'container', 'image', 'pod', "
        "'interaction', 'binding', 'connection')",
    )

    # Restore 0009's parts subtype allow-list (drop 'compose'). Any
    # compose-subtype rows would fail this CHECK on a clean downgrade
    # against a DB that has such rows — that's the correct behaviour:
    # you can't downgrade past a feature whose data is still in use.
    op.execute(
        "ALTER TABLE parts DROP CONSTRAINT ck_parts_subtype_allowed"
    )
    op.create_check_constraint(
        "subtype_allowed",
        "parts",
        "subtype IN ('software', 'container', 'image', 'pod')",
    )
