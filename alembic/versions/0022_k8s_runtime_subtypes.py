"""seven new k8s runtime subtypes + templates (#91)

Catalog gains structured vocabulary for the K8s runtime objects the
WatcherVault Helm chart actually creates. Driven by titan-archaedas#9.

Adds seven part subtypes and seeds a v1.0.0 active template for each.
The templates' bodies carry their own slot guidance per the
`feedback_skill_template_decoupling.md` memory (per-section guidance
lives in template bodies, not in skills). `/register-part` stays
template-agnostic.

Subtypes added:
- `deployment`    long-running replicated workload
- `statefulset`   replicated workload with stable identity + per-pod volumes
- `service`       stable network endpoint over a set of pods
- `ingress`       L7 HTTP(S) router with host/path rules
- `secret`        opaque sensitive K/V (catalog stores key names only)
- `configmap`     non-sensitive K/V
- `job`           run-to-completion workload

The existing `pod` subtype is intentionally not touched here — its
semantics shift to "pod spec" is bundled with C (the container/pod
content shift). See archaedas#9 for the locked plan.

Init container modeling is deferred to a v1.1 follow-up after C lands;
template bodies acknowledge their absence rather than ship a half-baked
sub-shape. Probe shape is captured in markdown sub-sections on the
controller bodies (no structured `probe` sub-shape in v1).

Schema changes:
- extend `ck_parts_subtype_allowed` from 5 to 12 values (drop+recreate)
- extend `ck_part_subtype_proposals_new_subtype_allowed` to match
- extend `ck_templates_kind_allowed` to admit the 7 new template kinds
- seed 7 new `templates` rows + matching `template_versions` rows
  (v1.0.0, status='active', accepted_at=now())

The router-side `PART_SUBTYPES` tuple in `src/schemas.py` and the
model-level CHECK in `src/models.py` mirror this migration so the
in-process app boots against the new enum.

Revision ID: 0022
Revises: 0021
Create Date: 2026-05-17
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ============================================================
# Template bodies (v1.0.0 each)
# ============================================================

DEPLOYMENT_TEMPLATE_V1 = """\
<!-- template: deployment@<template-version> -->

# <deployment-name>

**Type:** Deployment (Kubernetes)
**Owner:** <team or person>
**Image spec:** <container-part-name> (referenced via `runs` Connection contract)
**Replicas:** <number>
**Project:** <slug, optional>

> **DELETE WHEN FILLING IN.** Everything in this blockquote is guidance
> for whoever fills the template; strip the entire block before POSTing.
>
> A Deployment Part represents a long-running, replicated workload
> managed by the Kubernetes Deployment controller. It is the
> orchestrator — it references a container-spec (image + command) via
> a `runs` Connection contract, binds environment via `consumed-by`
> contracts from Secret / ConfigMap Parts, and is fronted by a Service
> via that Service's `selects` contract.
>
> Slot guidance:
> - **Replicas:** the desired pod count. One number.
> - **Image spec:** the canonical name of the Container Part that
>   describes the image+command tuple. The `runs` contract is the
>   load-bearing wiring; this body line is a human-readable pointer.
> - **Env from:** which Secret / ConfigMap Parts this Deployment
>   reads env vars from, and which keys. Pair with `consumed-by`
>   contracts pointing from the Secret/ConfigMap to this Deployment.
> - **Update strategy:** RollingUpdate (default) or Recreate; include
>   `maxSurge` / `maxUnavailable` if non-default.
> - **Probes:** liveness / readiness paths, ports, periods. Markdown
>   sub-section; v1 has no structured probe sub-shape.
>
> Init containers are not modeled in v1 (v1.1 follow-up after the
> container-spec semantics shift lands). The catalog stays silent
> on init containers for now, matching its current state.
>
> `name` must be a slug: lowercase letters, digits, hyphens; 1–64
> chars; no leading/trailing hyphen. Convention: chart-resource-name
> with a `-deployment` suffix (e.g. `watchervault-tyr-deployment`).

## Purpose

Two to four sentences. What workload does this Deployment run, and
what role does it play in the chart? Keep it operational — "what" /
"why" rather than "how."

## Env from

Which Secret / ConfigMap Parts supply env vars, and which keys are
consumed:

- secret/`<name>`: `<KEY_1>`, `<KEY_2>`
- configmap/`<name>`: `<KEY_3>`

Each line should correspond to a `consumed-by` Connection contract
from the named Secret/ConfigMap Part to this Deployment.

## Update strategy

RollingUpdate / Recreate, plus `maxSurge` / `maxUnavailable` if
non-default. One short paragraph.

## Probes

- **Liveness:** `<path>` on port `<port>`, period `<seconds>`
- **Readiness:** `<path>` on port `<port>`, period `<seconds>`

## Notes

Anything not captured above — resource requests/limits, node
selectors / tolerations / affinity, security context overrides,
deployment-specific quirks.
"""


STATEFULSET_TEMPLATE_V1 = """\
<!-- template: statefulset@<template-version> -->

# <statefulset-name>

**Type:** StatefulSet (Kubernetes)
**Owner:** <team or person>
**Image spec:** <container-part-name> (referenced via `runs` Connection contract)
**Replicas:** <number>
**Headless service:** <service-part-name>
**Project:** <slug, optional>

> **DELETE WHEN FILLING IN.** Everything in this blockquote is guidance
> for whoever fills the template; strip the entire block before POSTing.
>
> A StatefulSet Part represents a replicated workload with stable pod
> identity (pod-0, pod-1, …), ordered start/stop, and per-pod
> persistent volumes. Use for stateful workloads (databases, queues,
> caches) where pod identity or per-pod storage matters.
>
> StatefulSet is a separate Part subtype from Deployment because the
> shape differences are real: `volumeClaimTemplates`, ordered pod
> management, headless-service binding. A Deployment with empty
> volume-claim slots isn't a stateful workload — it's just a
> confusing Deployment.
>
> Slot guidance mirrors `deployment`'s slots, plus:
> - **Headless service:** the service-part used for stable per-pod
>   DNS (Service with `ClusterIP: None`). Required for StatefulSet
>   pod identity.
> - **Volume claim templates:** named PVCs the StatefulSet creates
>   per-pod. Cover purpose, storage class, size, access mode.
> - **Pod management policy:** OrderedReady (default) or Parallel.
>
> `name` convention: `<chart-resource>-statefulset` (e.g.
> `watchervault-postgres-statefulset`).

## Purpose

Two to four sentences. Why this workload is stateful — what data /
identity guarantee makes a Deployment insufficient.

## Env from

Which Secret / ConfigMap Parts supply env vars, and which keys.

- secret/`<name>`: `<KEY_1>`
- configmap/`<name>`: `<KEY_2>`

## Volume claim templates

Per-pod persistent volumes the StatefulSet creates:

| Name        | Purpose                       | Storage class | Size  | Access mode    |
| ----------- | ----------------------------- | ------------- | ----- | -------------- |
| `<name>`    | <what it stores>              | <class>       | <Gi>  | ReadWriteOnce  |

## Pod management policy

OrderedReady (default) / Parallel. Note any specific reason for the
choice.

## Probes

- **Liveness:** `<path>` on port `<port>`, period `<seconds>`
- **Readiness:** `<path>` on port `<port>`, period `<seconds>`

## Notes

Anything not captured above — backup / restore coupling, snapshot
strategy, scaling caveats.
"""


SERVICE_TEMPLATE_V1 = """\
<!-- template: service@<template-version> -->

# <service-name>

**Type:** Service (Kubernetes)
**Owner:** <team or person>
**Service type:** ClusterIP / NodePort / LoadBalancer
**Selects:** <controller-part-name> (referenced via `selects` Connection contract)
**Project:** <slug, optional>

> **DELETE WHEN FILLING IN.** Everything in this blockquote is guidance
> for whoever fills the template; strip the entire block before POSTing.
>
> A Service Part represents a stable network endpoint over a set of
> pods. The catalog records `type`, `port list`, and the controller
> it routes to — the actual label-selector matching is left implicit;
> the `selects` Connection contract names which Deployment /
> StatefulSet's pods this Service fronts.
>
> Headless Services (`ClusterIP: None`) used for StatefulSet pod
> identity are still modeled here — note `headless: true` in the
> Notes section so readers know this Service doesn't load-balance.
>
> `name` convention: `<chart-resource>-service` (e.g.
> `watchervault-tyr-service`).

## Purpose

Two to four sentences. What this Service exposes and to whom
(other in-cluster services? An Ingress? External via NodePort /
LoadBalancer?).

## Ports

| Name        | Port | Target port | Protocol |
| ----------- | ---- | ----------- | -------- |
| <name>      | 80   | 8000        | TCP      |

## Selector

The Deployment / StatefulSet this Service fronts is named in the
`selects` Connection contract; label-based wiring is K8s
implementation detail not tracked here.

## Notes

Anything not captured above — session affinity, `externalTrafficPolicy`,
headless flag, IPv6 dual-stack settings, annotations that change
behavior (e.g. cloud-LB tuning).
"""


INGRESS_TEMPLATE_V1 = """\
<!-- template: ingress@<template-version> -->

# <ingress-name>

**Type:** Ingress (Kubernetes)
**Owner:** <team or person>
**Ingress class:** <class-name, e.g. nginx>
**Project:** <slug, optional>

> **DELETE WHEN FILLING IN.** Everything in this blockquote is guidance
> for whoever fills the template; strip the entire block before POSTing.
>
> An Ingress Part represents an L7 HTTP(S) router fronting one or more
> Services in the cluster. Backends are NOT slots on the Ingress —
> they're `routes-to` Connection contracts pointing at the named
> Services. Per host/path rule, one contract entry.
>
> Route rules are a markdown table sub-shape on this body; v1 does
> not introduce a separate `route` Connection contract (the rules
> are intrinsic to the Ingress object spec and the table reads
> cleanly).
>
> TLS is captured as a markdown sub-section referencing the Secret
> Part that holds the cert (`tls-secret`). The catalog does not
> model cert-manager `Issuer` / `Certificate` resources in v1.
>
> `name` convention: `<chart-name>-ingress` (e.g.
> `watchervault-ingress`). One Ingress Part per actual Ingress
> object even if it carries many host rules.

## Purpose

Two to four sentences. What external surface this Ingress exposes,
and the rough traffic shape (browser? API client? webhook
receiver?).

## Routes

| Host                                   | Path     | Backend service              | Notes                  |
| -------------------------------------- | -------- | ---------------------------- | ---------------------- |
| <host.example.com>                     | `/`      | <service-part-name>          | <e.g. `/api/*` prefix> |

Each row should correspond to a `routes-to` Connection contract
from this Ingress to the named Service Part.

## TLS

- **Hosts:** <hostnames covered by this cert>
- **Secret:** secret/`<tls-secret-name>` (cert + key live in this
  Secret; values never stored in the catalog)
- **Issuer:** <if managed by cert-manager, name the Issuer>

## Notes

Anything not captured above — annotations that change behavior
(rate-limiting, body-size, ingress-controller-specific tuning),
HTTPS redirect policy, websocket / SSE long-poll support, custom
error pages.
"""


SECRET_TEMPLATE_V1 = """\
<!-- template: secret@<template-version> -->

# <secret-name>

**Type:** Secret (Kubernetes)
**Owner:** <team or person>
**Source:** chart-managed / externally-provided
**Project:** <slug, optional>

> 🔒 **NEVER STORE VALUES IN THE CATALOG.** This Part records the
> Secret's *key names* and *source*. The actual values live in the
> cluster (or the deployer's secret manager) and must never appear
> in any field of this Part body. mimiron's UI also surfaces a
> sensitive-data banner on Secret PartDetail pages as a second line
> of defense.
>
> **DELETE WHEN FILLING IN.** Everything in this blockquote is guidance
> for whoever fills the template; strip the entire block before POSTing.
>
> A Secret Part represents an opaque sensitive K/V resource in the
> cluster. Catalog tracks: which keys it carries, which Deployments /
> StatefulSets / Jobs consume which keys (via `consumed-by`
> contracts), and whether the Secret is managed by the chart or
> provided externally (operator-bootstrapped, sealed-secrets, etc.).
>
> `name` convention: `<chart-resource>-secret` or
> `<chart-resource>` if the chart calls it that already (e.g.
> `watchervault-secret`).

## Purpose

One to two sentences. Why this Secret exists and what consumes it.

## Keys

Key names only — never values.

| Key                    | Consumed by                                    | Notes                              |
| ---------------------- | ---------------------------------------------- | ---------------------------------- |
| `DATABASE_URL`         | deployment/`<deployment-part-name>`            | <e.g. asyncpg DSN>                 |
| `POSTGRES_PASSWORD`    | statefulset/`<statefulset-part-name>`          | <e.g. server-side superuser>       |

Each row's consumer should correspond to a `consumed-by` Connection
contract from this Secret to the named Deployment / StatefulSet /
Job Part.

## Source

- **chart-managed:** the chart's `templates/secret.yaml` creates
  this Secret from values (typically dev defaults).
- **externally-provided:** the chart references the Secret name but
  does NOT create it; an operator / sealed-secret / external-secret
  controller seeds the values.

## Rotation

How values are rotated, by whom, on what cadence. If externally
provided, who owns rotation.

## Notes

Anything not captured above — TLS cert lifecycle (if this is a
TLS Secret), known consumers outside the catalog, audit
requirements.
"""


CONFIGMAP_TEMPLATE_V1 = """\
<!-- template: configmap@<template-version> -->

# <configmap-name>

**Type:** ConfigMap (Kubernetes)
**Owner:** <team or person>
**Source:** chart-managed / externally-provided
**Project:** <slug, optional>

> **DELETE WHEN FILLING IN.** Everything in this blockquote is guidance
> for whoever fills the template; strip the entire block before POSTing.
>
> A ConfigMap Part represents a non-sensitive K/V resource in the
> cluster. Mirrors `secret` minus the confidentiality marker — values
> here are non-sensitive, so the catalog body MAY record the
> deployed values when that helps readers, but it is NOT obligated
> to (the cluster remains the source of truth).
>
> `name` convention: `<chart-resource>-configmap` or
> `<chart-resource>` if the chart calls it that.

## Purpose

One to two sentences. Why this ConfigMap exists and what consumes
it.

## Keys

| Key                  | Value (optional)            | Consumed by                                    | Notes                       |
| -------------------- | --------------------------- | ---------------------------------------------- | --------------------------- |
| `POSTGRES_USER`      | `titan` (chart default)     | statefulset/`<statefulset-part-name>`          | DB superuser name           |
| `TYR_UPSTREAM`       | `http://<svc>.<ns>.svc...`  | deployment/`<deployment-part-name>`            | Upstream proxy target       |

Each row's consumer should correspond to a `consumed-by` Connection
contract from this ConfigMap to the named Deployment / StatefulSet /
Job Part.

## Source

- **chart-managed:** the chart's `templates/configmap.yaml` creates
  this ConfigMap from values.
- **externally-provided:** the chart references the ConfigMap name
  but does NOT create it.

## Notes

Anything not captured above — interpolation rules, multi-line
config files mounted as keys, known consumers outside the catalog.
"""


JOB_TEMPLATE_V1 = """\
<!-- template: job@<template-version> -->

# <job-name>

**Type:** Job (Kubernetes)
**Owner:** <team or person>
**Image spec:** <container-part-name> (referenced via `runs` Connection contract)
**Project:** <slug, optional>

> **DELETE WHEN FILLING IN.** Everything in this blockquote is guidance
> for whoever fills the template; strip the entire block before POSTing.
>
> A Job Part represents a run-to-completion workload. Shape mirrors
> `deployment` minus replicas, plus completion semantics
> (`backoffLimit`, `completions`, `parallelism`).
>
> Typical use: schema migrations, one-shot data-loading, cron-equiv
> single-runs (for repeating schedules use a CronJob; not modeled
> in v1).
>
> Env from / probes / image-spec slots are identical in shape to
> `deployment`; init containers are likewise deferred to v1.1.
>
> `name` convention: `<chart-resource>-job` (e.g.
> `watchervault-migrate-job`).

## Purpose

One to three sentences. What this Job does, when it runs (helm hook?
manual `kubectl create job`?), and what it depends on.

## Completion semantics

- **`backoffLimit`:** <number> (retries before marking Failed)
- **`completions`:** <number> (typically 1 for a one-shot)
- **`parallelism`:** <number> (typically 1 for an ordered one-shot)
- **`activeDeadlineSeconds`:** <if set>
- **`ttlSecondsAfterFinished`:** <if set; controls cleanup of Job + pods>

## Env from

Which Secret / ConfigMap Parts supply env vars, and which keys.

- secret/`<name>`: `<KEY_1>`
- configmap/`<name>`: `<KEY_2>`

## Notes

Anything not captured above — pre/post-install hook semantics (if
this Job is a Helm hook), upstream dependencies that must be ready
before the Job runs, observability for the Job's output.
"""


_TEMPLATES_TO_SEED = (
    ("deployment", DEPLOYMENT_TEMPLATE_V1),
    ("statefulset", STATEFULSET_TEMPLATE_V1),
    ("service", SERVICE_TEMPLATE_V1),
    ("ingress", INGRESS_TEMPLATE_V1),
    ("secret", SECRET_TEMPLATE_V1),
    ("configmap", CONFIGMAP_TEMPLATE_V1),
    ("job", JOB_TEMPLATE_V1),
)


# ============================================================
# Constraint string literals — kept here as constants so the
# upgrade + downgrade pair can't accidentally diverge.
# ============================================================

_OLD_PARTS_SUBTYPE_LIST = (
    "'software', 'container', 'image', 'pod', 'compose'"
)
_NEW_PARTS_SUBTYPE_LIST = (
    "'software', 'container', 'image', 'pod', 'compose', "
    "'deployment', 'statefulset', 'service', 'ingress', "
    "'secret', 'configmap', 'job'"
)

_OLD_TEMPLATES_KIND_LIST = (
    "'software', 'container', 'image', 'pod', 'compose', "
    "'interaction', 'binding', 'connection'"
)
_NEW_TEMPLATES_KIND_LIST = (
    "'software', 'container', 'image', 'pod', 'compose', "
    "'interaction', 'binding', 'connection', "
    "'deployment', 'statefulset', 'service', 'ingress', "
    "'secret', 'configmap', 'job'"
)


def upgrade() -> None:
    bind = op.get_bind()

    # ---------- Phase 1: extend parts.subtype allow-list ----------
    op.execute("ALTER TABLE parts DROP CONSTRAINT ck_parts_subtype_allowed")
    op.create_check_constraint(
        "subtype_allowed",
        "parts",
        f"subtype IN ({_NEW_PARTS_SUBTYPE_LIST})",
    )

    # ---------- Phase 2: extend part_subtype_proposals.new_subtype ----
    # Migration 0011 created this CHECK via `sa.CheckConstraint(
    # name="ck_part_subtype_proposals_new_subtype_allowed")` inside
    # `op.create_table`. The metadata naming convention then prefixed
    # the literal name again to 71 chars, which SQLAlchemy
    # auto-truncates with a deterministic 4-char hash suffix before
    # sending to PostgreSQL — so the stored name is something like
    # `ck_part_subtype_proposals_ck_part_subtype_propos_<hex4>`,
    # unguessable without looking it up. We use the same
    # pg_constraint definition-pattern lookup that migration 0017 used
    # for the equivalent `connection_type` constraint on the sibling
    # `contract_subtype_proposals` table. The recreate uses the short
    # `new_subtype_allowed` constraint name so the convention produces
    # a clean single-prefix
    # `ck_part_subtype_proposals_new_subtype_allowed` (45 chars). The
    # model's `name=` kwarg in src/models.py still asks for the
    # doubled form; aligning that is the
    # naming-convention-hygiene ticket and not in scope here.
    bind = op.get_bind()
    proposal_ck_name = bind.execute(
        sa.text(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = 'part_subtype_proposals'::regclass "
            "  AND contype = 'c' "
            "  AND pg_get_constraintdef(oid) LIKE "
            "      '%new_subtype%software%compose%'"
        )
    ).scalar_one()
    op.execute(
        f'ALTER TABLE part_subtype_proposals DROP CONSTRAINT "{proposal_ck_name}"'
    )
    op.create_check_constraint(
        "new_subtype_allowed",
        "part_subtype_proposals",
        f"new_subtype IN ({_NEW_PARTS_SUBTYPE_LIST})",
    )

    # ---------- Phase 3: extend templates.kind allow-list ----------
    op.execute(
        "ALTER TABLE templates DROP CONSTRAINT ck_templates_kind_allowed"
    )
    op.create_check_constraint(
        "kind_allowed",
        "templates",
        f"kind IN ({_NEW_TEMPLATES_KIND_LIST})",
    )

    # ---------- Phase 4: seed 7 new templates at v1.0.0 active ----
    for kind, markdown in _TEMPLATES_TO_SEED:
        bind.execute(
            sa.text("INSERT INTO templates (kind) VALUES (:kind)"),
            {"kind": kind},
        )
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
    bind = op.get_bind()

    # ---------- Phase 4 reversed: strip new template versions + rows ----
    new_kinds = tuple(k for k, _ in _TEMPLATES_TO_SEED)
    placeholders = ", ".join(f":k{i}" for i in range(len(new_kinds)))
    params = {f"k{i}": k for i, k in enumerate(new_kinds)}
    bind.execute(
        sa.text(
            f"DELETE FROM template_versions WHERE template_id IN "
            f"(SELECT id FROM templates WHERE kind IN ({placeholders}))"
        ),
        params,
    )
    bind.execute(
        sa.text(f"DELETE FROM templates WHERE kind IN ({placeholders})"),
        params,
    )

    # ---------- Phase 3 reversed: restore templates.kind allow-list ----
    op.execute(
        "ALTER TABLE templates DROP CONSTRAINT ck_templates_kind_allowed"
    )
    op.create_check_constraint(
        "kind_allowed",
        "templates",
        f"kind IN ({_OLD_TEMPLATES_KIND_LIST})",
    )

    # ---------- Phase 2 reversed: restore part_subtype_proposals.new_subtype ----
    # The upgrade left this constraint at the single-prefix
    # alembic-conventional name (since op.create_check_constraint with
    # a short name applies the convention exactly once). Drop *that*
    # name — not the doubled-then-hashed original 0011 created.
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
    # Any new-subtype rows would fail this CHECK on downgrade against a
    # DB that has such rows — that's the correct behaviour: you can't
    # downgrade past a feature whose data is still in use.
    op.execute("ALTER TABLE parts DROP CONSTRAINT ck_parts_subtype_allowed")
    op.create_check_constraint(
        "subtype_allowed",
        "parts",
        f"subtype IN ({_OLD_PARTS_SUBTYPE_LIST})",
    )
