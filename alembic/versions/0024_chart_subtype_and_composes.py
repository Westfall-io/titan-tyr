"""chart part subtype + composes connection_type (replaces member-of) (#100, #101)

Combined structural drop for two paired tickets:

- **#101 (C)** — replace `member-of` with `composes` as the catalog's
  umbrella-containment edge. Direction flips top-down: source-of-truth
  files (chart, compose.yaml) read parent → child. The four existing
  `container -member-of-> compose` rows in the watchervault project
  flip in-place to `compose -composes-> container` (same UUIDs, same
  version chain).

- **#100** — add `chart` as the 13th part subtype + seed `chart@1.0.0`
  template. K8s analog to `compose`: the umbrella that names a Helm
  release. Pair-rule extension `chart -composes-> {deployment,
  statefulset, job, service, ingress, secret, configmap}` lives in
  `src/routers/_rules.py`, not in schema.

Both ship in one migration because #100's `composes` pair-rule
extension is inexpressible until `composes` exists in the
`connection_type` CHECK — committing the chart subtype without the
connection_type swap would leave chart parts with no valid outgoing
edges. See [archaedas#9 v2 design](https://github.com/Westfall-io/titan-archaedas/issues/9#issuecomment-4505045831).

Out of scope for this migration (operational, post-deploy):

- `container@4.0.0` and `pod@2.0.0` template body shifts — filed as
  template proposals via the API after this lands (per project
  convention: alembic seeds v1.0.0 only; subsequent versions go
  through `/propose-template-change` + `/accept-template-proposal`).
- PUT body updates on the four `*-local` container parts — filed via
  `/update-part` after the template proposals land.

Schema changes:

- Extend `ck_parts_subtype_allowed` from 12 → 13 (add `chart`).
- Extend `ck_part_subtype_proposals_new_subtype_allowed` to match.
- Extend `ck_templates_kind_allowed` to admit `chart`.
- Modify `ck_contracts_connection_type_allowed`: drop `member-of`,
  add `composes`.
- Modify `ck_contract_subtype_proposals_connection_type_allowed`: same.
- Data: flip all `contracts` rows with `connection_type = 'member-of'`
  to `connection_type = 'composes'` with `owner_part_id` ↔
  `counterparty_part_id` swapped. Same swap applied to any open
  `contract_subtype_proposals` rows currently proposing
  `new_connection_type = 'member-of'`.
- Seed one new `templates` row + matching `template_versions` row at
  v1.0.0 active for `chart`.

Order matters: the `member-of` → `composes` data flip must happen
**after** `composes` is admitted by the CHECK and **before**
`member-of` is dropped. Migration sequences as:

1. Extend the subtype CHECKs to admit `chart` (no data implications).
2. Extend the connection_type CHECKs to admit `composes` (no rows use
   it yet; pure widening).
3. Flip `member-of` → `composes` rows on `contracts` + open
   subtype-proposals (data movement under the wider CHECK).
4. Tighten the connection_type CHECKs to drop `member-of` (now safe;
   no rows reference it).
5. Extend templates.kind CHECK + seed `chart@1.0.0` (independent).

Revision ID: 0024
Revises: 0023
Create Date: 2026-05-23
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ============================================================
# chart@1.0.0 template body
# ============================================================
#
# Slot guidance per the #100 design comment. The body carries its own
# per-slot guidance (memory: skill-template decoupling — per-section
# guidance lives in template bodies, not skills). `/register-part`
# stays template-agnostic.
#
# Chart vs the source `software` part:
#   - `software` = the chart source (the bytes in `helm/<chart>/`).
#   - `chart` = a concrete deployed release of that chart in a
#     specific cluster/namespace under a specific release name.
#
# The two new slots from #100's Q3:
#   - `chart_repository` — for charts pulled from an external Helm
#     repo (e.g. https://charts.bitnami.com/...) rather than the
#     source software part's own repo.
#   - `release_namespace` + `release_name` as separate slots — Helm
#     allows the same chart released into multiple namespaces with
#     different names.
#
# `chart → software` edge is intentionally NOT modeled in v1 (#100
# Q4 = omit). The source software part is referenced only by the
# `Source software part` body slot.

CHART_TEMPLATE_V1 = """\
<!-- template: chart@<template-version> -->

# <chart-release-name>

**Type:** Helm chart release
**Owner:** <team or person>
**Chart name:** <chart-name>
**Chart version:** <semver of the Helm chart>
**App version:** <semver of the released image set>
**Source software part:** <software-part-name, body slot only — no edge in v1>
**Chart repository:** <https://... OR `in-repo` if vendored alongside the source software>
**Namespace:** <kubernetes namespace deployed into>
**Release namespace:** <namespace the Helm release object lives in; usually same as Namespace above>
**Release name:** <Helm release name; the `helm install <release-name>` argument>
**Values file:** <path or URL to the values overlay this release used (e.g. `helm/watchervault/values-prod.yaml`)>
**Project:** <slug, optional>

> **DELETE WHEN FILLING IN.** Everything in this blockquote is
> guidance for whoever fills the template; strip the entire block
> before POSTing.
>
> A Chart Part is the **umbrella** that names a deployed Helm
> release. It's the K8s analog of `compose`: where a `compose` Part
> aggregates one or more `container` Parts via `composes` Connection
> contracts, a `chart` Part aggregates the K8s resources the release
> creates (`deployment`, `statefulset`, `job`, `service`, `ingress`,
> `secret`, `configmap`) via `composes` Connection contracts.
>
> Slot guidance:
>
> - **Chart name** vs **App version:** the chart name is the Helm
>   chart identifier (the directory under `helm/`); the app version
>   is the image-set version the chart deploys (e.g. `0.31.0` for
>   `titan-tyr`). They move independently — bumping the chart for a
>   manifest tweak doesn't bump the app version.
> - **Source software part:** body-slot reference to the `software`
>   Part that owns `helm/<chart-name>/`. No `chart → software` edge
>   in v1 — that edge is deferred (see #100 Q4). Use the slot value
>   so the link is at least human-discoverable.
> - **Chart repository:** if the chart is vendored in the source
>   software's own repo (the WatcherVault case), write `in-repo`.
>   If pulled from an external Helm registry, the full URL of the
>   repository (`https://charts.bitnami.com/bitnami`,
>   `oci://registry-1.docker.io/bitnamicharts`, etc.).
> - **Namespace** vs **Release namespace:** in 99% of cases these
>   are the same; Helm distinguishes them (a release object can
>   live in a different namespace than the resources it deploys).
>   Set both even when identical so consumers don't have to assume.
> - **Release name:** Helm allows the same chart to be installed
>   multiple times in the same cluster under different release
>   names (e.g. `watchervault-prod` and `watchervault-staging`).
>   This slot is what disambiguates this Chart Part from a sibling
>   release of the same chart.
> - **Values file:** the path or URL to the values overlay this
>   specific release was installed with. The chart bytes (in the
>   source software part) are reproducible; the values overlay is
>   what makes *this* release distinct from others.
>
> `name` must be a slug: lowercase letters, digits, hyphens; 1–64
> chars; no leading/trailing hyphen. Convention: `<release-name>` or
> `<release-name>-chart` (e.g. `watchervault`, `watchervault-chart`).

## Purpose

Two to four sentences. What does this Helm release deploy, and what
role does it play in the system? Operational framing — "what" / "why"
rather than chart internals.

## What this release composes

Brief inventory of the K8s resources this chart creates and what they
do together. Pair each entry with a `chart -composes-> <part>`
Connection contract so the catalog has the structural edge in addition
to this human-readable list:

- deployment/`<part-name>`: <one-line role>
- statefulset/`<part-name>`: <one-line role>
- job/`<part-name>`: <one-line role>
- service/`<part-name>`: <one-line role>
- ingress/`<part-name>`: <one-line role>
- secret/`<part-name>`: <one-line role>
- configmap/`<part-name>`: <one-line role>

(Omit lines for resource kinds this release doesn't create.)

## Operational notes

Anything a future operator needs to know that isn't in the chart
itself: known upgrade gotchas, where the values file lives, how to
roll back, whether this release is managed by an external tool
(ArgoCD `Application`, Flux `HelmRelease`).
"""


# ============================================================
# Constraint string literals — kept here as constants so the
# upgrade + downgrade pair can't accidentally diverge.
# ============================================================

_OLD_PARTS_SUBTYPE_LIST = (
    "'software', 'container', 'image', 'pod', 'compose', "
    "'deployment', 'statefulset', 'service', 'ingress', "
    "'secret', 'configmap', 'job'"
)
_NEW_PARTS_SUBTYPE_LIST = (
    "'software', 'container', 'image', 'pod', 'compose', "
    "'deployment', 'statefulset', 'service', 'ingress', "
    "'secret', 'configmap', 'job', 'chart'"
)

_OLD_TEMPLATES_KIND_LIST = (
    "'software', 'container', 'image', 'pod', 'compose', "
    "'interaction', 'binding', 'connection', "
    "'deployment', 'statefulset', 'service', 'ingress', "
    "'secret', 'configmap', 'job'"
)
_NEW_TEMPLATES_KIND_LIST = (
    "'software', 'container', 'image', 'pod', 'compose', "
    "'interaction', 'binding', 'connection', "
    "'deployment', 'statefulset', 'service', 'ingress', "
    "'secret', 'configmap', 'job', 'chart'"
)

# Connection-type CHECKs — drop `member-of`, add `composes`. Phase
# ordering uses an intermediate `_WIDENED_CONNECTION_TYPES` that
# admits both (the data flip happens under this CHECK, then we
# tighten to drop member-of).
_OLD_CONNECTION_TYPES = (
    "'builds-from', 'instantiates', 'runs', "
    "'member-of', 'depends-on', 'submodule', 'serves-static', "
    "'selects', 'routes-to', 'consumed-by'"
)
_WIDENED_CONNECTION_TYPES = (
    "'builds-from', 'instantiates', 'runs', "
    "'member-of', 'composes', 'depends-on', 'submodule', 'serves-static', "
    "'selects', 'routes-to', 'consumed-by'"
)
_NEW_CONNECTION_TYPES = (
    "'builds-from', 'instantiates', 'runs', "
    "'composes', 'depends-on', 'submodule', 'serves-static', "
    "'selects', 'routes-to', 'consumed-by'"
)


def upgrade() -> None:
    bind = op.get_bind()

    # ---------- Phase 1: extend parts.subtype to admit `chart` ----------
    op.execute("ALTER TABLE parts DROP CONSTRAINT ck_parts_subtype_allowed")
    op.create_check_constraint(
        "subtype_allowed",
        "parts",
        f"subtype IN ({_NEW_PARTS_SUBTYPE_LIST})",
    )

    # ---------- Phase 2: extend part_subtype_proposals.new_subtype --
    # Migration 0022 already converted this constraint to the
    # single-prefix name `ck_part_subtype_proposals_new_subtype_allowed`;
    # 0024 can drop it directly by that clean name.
    op.execute(
        "ALTER TABLE part_subtype_proposals "
        "DROP CONSTRAINT ck_part_subtype_proposals_new_subtype_allowed"
    )
    op.create_check_constraint(
        "new_subtype_allowed",
        "part_subtype_proposals",
        f"new_subtype IN ({_NEW_PARTS_SUBTYPE_LIST})",
    )

    # ---------- Phase 3: widen connection_type CHECKs to admit `composes` ----
    # Both old (`member-of`) and new (`composes`) values are valid in
    # this intermediate state; this lets the data flip happen without
    # violating either CHECK direction.
    op.execute(
        "ALTER TABLE contracts DROP CONSTRAINT ck_contracts_connection_type_allowed"
    )
    op.create_check_constraint(
        "connection_type_allowed",
        "contracts",
        f"connection_type IS NULL OR connection_type IN ({_WIDENED_CONNECTION_TYPES})",
    )
    op.execute(
        "ALTER TABLE contract_subtype_proposals "
        "DROP CONSTRAINT ck_contract_subtype_proposals_connection_type_allowed"
    )
    op.create_check_constraint(
        "connection_type_allowed",
        "contract_subtype_proposals",
        f"new_connection_type IS NULL OR new_connection_type IN ({_WIDENED_CONNECTION_TYPES})",
    )

    # ---------- Phase 4: flip member-of → composes rows ----------
    # Direction flip = swap owner ↔ counterparty AND change the label.
    # Single UPDATE per table so atomicity covers both columns + label
    # together. Existing contract identity (id, version chain) is
    # preserved; only the relationship direction + label change.
    #
    # Affected rows on the live watchervault catalog (per the v2
    # design close-out): 4 `container -member-of-> compose` edges from
    # the `*-local` parts. Test databases have 0 such rows.
    bind.execute(
        sa.text(
            """
            UPDATE contracts
               SET connection_type = 'composes',
                   owner_part_id = counterparty_part_id,
                   counterparty_part_id = owner_part_id
             WHERE connection_type = 'member-of'
            """
        )
    )
    # Same flip for any open subtype-shift proposals targeting member-of.
    # `contract_subtype_proposals` has new_owner_part_id /
    # new_counterparty_part_id (per src/models.py:726/729) only on
    # endpoint-shift proposals, NOT on connection_type proposals — the
    # subtype-shift proposal carries `new_connection_type` only. So
    # the label flip is sufficient on this table.
    bind.execute(
        sa.text(
            """
            UPDATE contract_subtype_proposals
               SET new_connection_type = 'composes'
             WHERE new_connection_type = 'member-of'
            """
        )
    )

    # ---------- Phase 5: tighten connection_type CHECKs (drop member-of) ----
    op.execute(
        "ALTER TABLE contracts DROP CONSTRAINT ck_contracts_connection_type_allowed"
    )
    op.create_check_constraint(
        "connection_type_allowed",
        "contracts",
        f"connection_type IS NULL OR connection_type IN ({_NEW_CONNECTION_TYPES})",
    )
    op.execute(
        "ALTER TABLE contract_subtype_proposals "
        "DROP CONSTRAINT ck_contract_subtype_proposals_connection_type_allowed"
    )
    op.create_check_constraint(
        "connection_type_allowed",
        "contract_subtype_proposals",
        f"new_connection_type IS NULL OR new_connection_type IN ({_NEW_CONNECTION_TYPES})",
    )

    # ---------- Phase 6: extend templates.kind + seed chart@1.0.0 ----
    op.execute(
        "ALTER TABLE templates DROP CONSTRAINT ck_templates_kind_allowed"
    )
    op.create_check_constraint(
        "kind_allowed",
        "templates",
        f"kind IN ({_NEW_TEMPLATES_KIND_LIST})",
    )
    bind.execute(
        sa.text("INSERT INTO templates (kind) VALUES ('chart')")
    )
    template_id = bind.execute(
        sa.text("SELECT id FROM templates WHERE kind = 'chart'")
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
        {"template_id": template_id, "markdown": CHART_TEMPLATE_V1},
    )


def downgrade() -> None:
    bind = op.get_bind()

    # ---------- Phase 6 reversed: strip chart template + tighten kind CHECK ----
    bind.execute(
        sa.text(
            "DELETE FROM template_versions WHERE template_id IN "
            "(SELECT id FROM templates WHERE kind = 'chart')"
        )
    )
    bind.execute(sa.text("DELETE FROM templates WHERE kind = 'chart'"))
    op.execute(
        "ALTER TABLE templates DROP CONSTRAINT ck_templates_kind_allowed"
    )
    op.create_check_constraint(
        "kind_allowed",
        "templates",
        f"kind IN ({_OLD_TEMPLATES_KIND_LIST})",
    )

    # ---------- Phase 5 reversed: widen connection_type CHECKs again ----
    op.execute(
        "ALTER TABLE contracts DROP CONSTRAINT ck_contracts_connection_type_allowed"
    )
    op.create_check_constraint(
        "connection_type_allowed",
        "contracts",
        f"connection_type IS NULL OR connection_type IN ({_WIDENED_CONNECTION_TYPES})",
    )
    op.execute(
        "ALTER TABLE contract_subtype_proposals "
        "DROP CONSTRAINT ck_contract_subtype_proposals_connection_type_allowed"
    )
    op.create_check_constraint(
        "connection_type_allowed",
        "contract_subtype_proposals",
        f"new_connection_type IS NULL OR new_connection_type IN ({_WIDENED_CONNECTION_TYPES})",
    )

    # ---------- Phase 4 reversed: flip composes → member-of rows back ----
    # Mirror of the up-direction flip: swap owner ↔ counterparty back
    # AND change the label back. This rewrites any composes-shape edges
    # added under the new ontology into member-of-shape, which under the
    # pre-#101 rules table is only valid for the (container, compose)
    # pair. If composes was used post-upgrade for any OTHER pair (e.g.
    # `chart -composes-> deployment`, or `deployment -composes-> pod`),
    # downgrade can't represent it — the row would re-enter the OLD
    # CHECK as a valid `member-of` shape but a structurally bogus pair
    # under the legacy CONNECTION_RULES. That's the correct behaviour:
    # you can't downgrade past a feature whose data is still in use.
    # The Phase 3-reversed step below will refuse to apply if such
    # rows remain (member-of CHECK will not admit them).
    bind.execute(
        sa.text(
            """
            UPDATE contracts
               SET connection_type = 'member-of',
                   owner_part_id = counterparty_part_id,
                   counterparty_part_id = owner_part_id
             WHERE connection_type = 'composes'
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE contract_subtype_proposals
               SET new_connection_type = 'member-of'
             WHERE new_connection_type = 'composes'
            """
        )
    )

    # ---------- Phase 3 reversed: tighten connection_type CHECKs (drop composes) ----
    op.execute(
        "ALTER TABLE contracts DROP CONSTRAINT ck_contracts_connection_type_allowed"
    )
    op.create_check_constraint(
        "connection_type_allowed",
        "contracts",
        f"connection_type IS NULL OR connection_type IN ({_OLD_CONNECTION_TYPES})",
    )
    op.execute(
        "ALTER TABLE contract_subtype_proposals "
        "DROP CONSTRAINT ck_contract_subtype_proposals_connection_type_allowed"
    )
    op.create_check_constraint(
        "connection_type_allowed",
        "contract_subtype_proposals",
        f"new_connection_type IS NULL OR new_connection_type IN ({_OLD_CONNECTION_TYPES})",
    )

    # ---------- Phase 2 reversed: restore part_subtype_proposals.new_subtype ----
    op.execute(
        "ALTER TABLE part_subtype_proposals "
        "DROP CONSTRAINT ck_part_subtype_proposals_new_subtype_allowed"
    )
    op.create_check_constraint(
        "new_subtype_allowed",
        "part_subtype_proposals",
        f"new_subtype IN ({_OLD_PARTS_SUBTYPE_LIST})",
    )

    # ---------- Phase 1 reversed: restore parts.subtype allow-list ----
    # Any chart-subtype rows would fail this CHECK on downgrade against
    # a DB that has such rows — that's the correct behaviour: you
    # can't downgrade past a feature whose data is still in use.
    op.execute("ALTER TABLE parts DROP CONSTRAINT ck_parts_subtype_allowed")
    op.create_check_constraint(
        "subtype_allowed",
        "parts",
        f"subtype IN ({_OLD_PARTS_SUBTYPE_LIST})",
    )
