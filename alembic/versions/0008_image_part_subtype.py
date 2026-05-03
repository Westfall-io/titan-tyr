"""image part subtype + image template

#35: add the `image` Part subtype, representing the built artifact
between Software (the source repo) and Container (the running
instance). Unblocks two of the six `connection_type` labels from #32:

- `builds-from`: Software → Image (Dockerfile + CI)
- `instantiates`: Image → Container (or Pod, once #36 lands)

Schema changes in this revision:
- extend `ck_parts_subtype_allowed` from {software, container} to
  {software, container, image} (drop+recreate per the 0006 ordering
  pattern; no data UPDATE — existing rows stay valid)
- extend `ck_templates_kind_allowed` to admit 'image' (drop+recreate)
- seed `image` template at v1.0.0 active

The router-side `_PART_SUBTYPES_IMPLEMENTED` allow-set in
`src/routers/contracts.py` also extends to {software, container,
image}, which is what actually unblocks the two connection_type
labels above. The schema CHECK is the persistence guard; the router
check is the validation layer.

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-03
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


IMAGE_TEMPLATE_V1 = """\
<!-- template: image@<template-version> -->

# <image-name>

**Type:** Image
**Owner:** <team or person>
**Built from:** <software-part-name> (referenced via the `builds-from` Connection contract)
**Registry:** <registry URL or namespace, e.g. ghcr.io/westfall-io>

> **DELETE WHEN FILLING IN.** Everything in this blockquote is guidance
> for whoever fills the template; strip the entire block before POSTing.
>
> An Image Part represents a **built artifact** — a tagged Docker
> image, a Helm chart version, a packaged binary. It sits between the
> Software Part (the source repository that builds *into* the image)
> and the Container Part (the running instance of the image at a
> specific address in a specific environment).
>
> One Software Part typically has one Image Part (the canonical image
> built from main). One Image Part can have many Container Parts (one
> per environment).
>
> An Image Part participates in two `connection_type` labels from #32:
> - `builds-from` (Software → Image): the build-time relationship
>   declared in the Dockerfile + CI pipeline. The Image is the *output*
>   of the build; the Software is the *source*.
> - `instantiates` (Image → Container or Pod): the runtime
>   relationship — this image is what the running container instance
>   was started from. The Image is the *template*; the Container is
>   the *instance*.
>
> Note: titan-tyr stores `name`, `repo_uri`, `issue_tracker_uri`,
> `aliases`, `subtype`, and `version` separately on the API request —
> those JSON fields are canonical. The header above is for human
> readers; do not rely on it as machine-readable metadata.
>
> `name` must be a **slug**: lowercase letters, digits, and hyphens
> (1–64 chars, no leading/trailing hyphen). Naming convention:
> `<service>-image` for the canonical image built from the
> `<service>` software part (e.g. `payments-image` from
> `payments-service`). For images built from forks or feature
> branches, append a suffix (e.g. `payments-image-experimental`).
>
> `repo_uri` should point at the source repo that builds the image —
> typically the same `repo_uri` as the Software Part it is built
> from. The `builds-from` Connection contract is the canonical
> recording of that relationship; this field is for ad-hoc lookup.
>
> The HTML comment on the first line is a **template-version stamp**.
> Consuming skills (e.g. `/register-part`) substitute
> `<template-version>` with the active template version they fetched.
> Drift-detection tooling reads it back to compare against the
> current active template. Do not remove the line; do not hand-edit
> the value.

## Purpose

Two to four sentences. What does this image package and why does it
exist? Written for a reader with no prior context. Cover the runtime
shape (HTTP server? worker? CLI?), the base image lineage if relevant
(Alpine, Debian-slim, distroless, scratch), and any non-obvious
build characteristics.

## Pinned versions

The pinned tag, digest, or chart version this Image Part represents.
Update on every substantive build that supersedes the prior pin.

| Component | Pinned value                              | Notes                                |
| --------- | ----------------------------------------- | ------------------------------------ |
| tag       | <e.g. v1.2.3, latest, sha-abc123>         | <when this tag is rebuilt>           |
| digest    | <sha256:... if pinned by digest>          | <preferred for prod; tag for dev>    |
| registry  | <e.g. ghcr.io/westfall-io/payments>       | <full pull URL>                      |

## Build provenance

Two to four sentences. What CI pipeline produces this image, on what
trigger, with what cache strategy? Reference the `builds-from`
Connection contract for the binding agreement; this section is the
human-readable summary.

## Connections

The Connection contracts this Image Part participates in. Reference
contracts by their `<owner-name> → <counterparty-name>` endpoint pair,
not by `contract_id` (same convention as the Container template's
post-#34 Connections table — the graph is source of truth for the id).

| Connected to        | Connection type    | Contract reference                                      |
| ------------------- | ------------------ | ------------------------------------------------------- |
| <software-name>     | `builds-from`      | `<software-name> → <this-image>` (connection, builds-from) |
| <container-name>    | `instantiates`     | `<this-image> → <container-name>` (connection, instantiates) |

> **DELETE WHEN FILLING IN.** A typical Image has one inbound
> `builds-from` row (from the Software Part it is built from) and one
> or more outbound `instantiates` rows (one per Container Part it is
> run as). Direction matters: `builds-from` flows *into* the image
> from the source; `instantiates` flows *out* of the image to the
> runtime. The `pod` arm of `instantiates` blocks on titan-tyr#36
> until the Pod Part subtype lands.

## Notes

Anything not captured above — base image rotation cadence, vendored
binary lineage, CVE-tracking quirks, registry mirror configurations.
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
        "subtype IN ('software', 'container', 'image')",
    )

    # ---------- Phase 2: extend templates.kind allow-list ----------
    op.execute(
        "ALTER TABLE templates DROP CONSTRAINT ck_templates_kind_allowed"
    )
    op.create_check_constraint(
        "kind_allowed",
        "templates",
        "kind IN ('software', 'container', 'image', 'interaction', 'binding', 'connection')",
    )

    # ---------- Phase 3: seed the image template at v1.0.0 active ----------
    bind.execute(sa.text("INSERT INTO templates (kind) VALUES ('image')"))
    template_id = bind.execute(
        sa.text("SELECT id FROM templates WHERE kind = 'image'")
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
        {"template_id": template_id, "markdown": IMAGE_TEMPLATE_V1},
    )


def downgrade() -> None:
    bind = op.get_bind()

    # Strip the image template (versions first, then row).
    bind.execute(
        sa.text(
            "DELETE FROM template_versions WHERE template_id IN "
            "(SELECT id FROM templates WHERE kind = 'image')"
        )
    )
    bind.execute(sa.text("DELETE FROM templates WHERE kind = 'image'"))

    # Restore 0007's templates kind allow-list (drop 'image').
    op.execute(
        "ALTER TABLE templates DROP CONSTRAINT ck_templates_kind_allowed"
    )
    op.create_check_constraint(
        "kind_allowed",
        "templates",
        "kind IN ('software', 'container', 'interaction', 'binding', 'connection')",
    )

    # Restore 0007's parts subtype allow-list (drop 'image'). Any image-
    # subtype rows would fail this CHECK on a clean downgrade against a
    # DB that has such rows — that's the correct behaviour: you can't
    # downgrade past a feature whose data is still in use.
    op.execute(
        "ALTER TABLE parts DROP CONSTRAINT ck_parts_subtype_allowed"
    )
    op.create_check_constraint(
        "subtype_allowed",
        "parts",
        "subtype IN ('software', 'container')",
    )
