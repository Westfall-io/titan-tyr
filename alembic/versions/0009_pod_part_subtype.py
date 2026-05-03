"""pod part subtype + pod template

#36: add the `pod` Part subtype, the K8s sibling of `container`. A pod
is a scheduled unit of one or more co-located containers — different
orchestrator (Kubernetes vs Docker / compose), similar shape (a
runtime instance of one or more images at an address in an
environment).

Unblocks the remaining `pod` arms of the connection labels deferred
from #32:

- `instantiates`: Image → Pod (in addition to the container arm shipped
  in #35)
- `runs`: Pod → Software (in addition to the container arm)

Also relaxes the `binding` source rule in `src/routers/contracts.py`
from `subtype == "container"` to `subtype IN ("container", "pod")`.
The SysMLv2 binding spec was always permissive there; the code only
restricted to container because pod didn't exist yet.

Schema changes in this revision:
- extend `ck_parts_subtype_allowed` from {software, container, image}
  to {software, container, image, pod} (drop+recreate per the 0006
  ordering pattern; no data UPDATE — existing rows stay valid)
- extend `ck_templates_kind_allowed` to admit 'pod' (drop+recreate)
- seed `pod` template at v1.0.0 active

The router-side `_PART_SUBTYPES_IMPLEMENTED` allow-set in
`src/routers/contracts.py` also extends to include `pod`, which is
what actually unblocks the two connection_type label arms above. The
schema CHECK is the persistence guard; the router check is the
validation layer.

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-03
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


POD_TEMPLATE_V1 = """\
<!-- template: pod@<template-version> -->

# <pod-name>

**Type:** Pod
**Owner:** <team or person>
**Cluster:** <cluster name or context, e.g. prod-us-east-1>
**Namespace:** <k8s namespace>

> **DELETE WHEN FILLING IN.** Everything in this blockquote is guidance
> for whoever fills the template; strip the entire block before POSTing.
>
> A Pod Part represents a **K8s pod** — a scheduled unit of one or
> more co-located containers sharing a network namespace and storage
> volumes. It is the K8s sibling of a Container Part: same "runtime
> instance of an image at an address in an environment" mental
> model, different orchestrator.
>
> One Image Part can have many Pod Parts (one per environment, often
> multiple replicas per environment though the Pod Part is the
> *template*, not the live replica set). One Pod Part can host
> multiple containers (init containers, sidecars, the main app
> container) — list them in the Containers table below.
>
> A Pod Part participates in two `connection_type` labels and one
> `binding` arm:
> - `instantiates` (Image → Pod): an image is run as one of the
>   containers inside this pod. One row per container in the pod.
> - `runs` (Pod → Software): the pod hosts a specific software
>   process. Mirrors the Container `runs` row.
> - `binding` (Pod → Software): the runtime address binding (host,
>   port, scheme) at which the software process inside the pod is
>   reachable. Same shape as a Container binding; the API accepts
>   either container or pod as the binding owner since #36.
>
> Note: titan-tyr stores `name`, `repo_uri`, `issue_tracker_uri`,
> `aliases`, `subtype`, and `version` separately on the API request —
> those JSON fields are canonical. The header above is for human
> readers; do not rely on it as machine-readable metadata.
>
> `name` must be a **slug**: lowercase letters, digits, and hyphens
> (1–64 chars, no leading/trailing hyphen). Naming convention:
> mirror the K8s manifest name. For a Deployment-managed pod use
> `<service>-pod` (e.g. `payments-pod`); for a StatefulSet member
> include the ordinal-shape (`payments-statefulset-0`-style names
> drift across reschedules — prefer the workload name without the
> ordinal). For ad-hoc / one-off pods, append a suffix
> (`payments-pod-debug`).
>
> `repo_uri` should point at the repo that owns the K8s manifest
> (Helm chart, kustomize overlay, raw YAML). The `instantiates`
> Connection contracts are the canonical recording of which images
> the pod runs.
>
> The HTML comment on the first line is a **template-version stamp**.
> Consuming skills (e.g. `/register-part`) substitute
> `<template-version>` with the active template version they fetched.
> Drift-detection tooling reads it back to compare against the
> current active template. Do not remove the line; do not hand-edit
> the value.

## Purpose

Two to four sentences. What workload does this pod schedule, and why
is it deployed as a pod (rather than a single container)? Cover the
co-location reasoning if the pod has more than one container (sidecar
proxy? init container that warms a cache? log shipper?), the
controller that manages it (Deployment, StatefulSet, DaemonSet, Job),
and any non-obvious scheduling characteristics (node selectors,
tolerations, affinity).

## Containers

The containers that share this pod's network and storage. One row
per container — at minimum the main app container; init containers
and sidecars get their own rows. Each container references an Image
Part by name (the `instantiates` Connection contract for that pair
is the canonical wiring; this table is for human readers).

| Container name | Role        | Image part         | Notes                                       |
| -------------- | ----------- | ------------------ | ------------------------------------------- |
| <name>         | main / init / sidecar | <image-part-name> | <e.g. "blocks startup until X is ready">    |

## Networking

How is this pod reachable, and how does it reach out? Cover:

- **Service:** the K8s Service in front of the pod (ClusterIP /
  NodePort / LoadBalancer name + port mapping).
- **Ingress / Gateway:** if exposed externally, the Ingress or
  Gateway resource and its hostname.
- **Egress notes:** anything special about the pod's outbound
  traffic — egress NetworkPolicy, service mesh sidecar, restricted
  destinations.

## Replicas / scaling

The replica count or scaling controller. The Pod Part is the
*template*, not the live replica set, so this section is informational
("typically 3 replicas; HPA scales 2–10 on CPU > 70%"), not a live
metric. Update on every substantive scaling change.

## Pinned versions

The pinned image tags / chart versions this Pod Part represents.
Mirror the Image Parts referenced in Containers above. Update on
every substantive deploy that supersedes the prior pin.

| Component | Pinned value                              | Notes                                |
| --------- | ----------------------------------------- | ------------------------------------ |
| <image>   | <e.g. v1.2.3, sha-abc123>                 | <when this is rebuilt / redeployed>  |

## Connections

The Connection and Binding contracts this Pod Part participates in.
Reference contracts by their `<owner-name> → <counterparty-name>`
endpoint pair, not by `contract_id`.

| Connected to        | Contract type           | Contract reference                                              |
| ------------------- | ----------------------- | --------------------------------------------------------------- |
| <image-name>        | connection / `instantiates` | `<image-name> → <this-pod>` (one row per container)         |
| <software-name>     | connection / `runs`         | `<this-pod> → <software-name>`                              |
| <software-name>     | binding                     | `<this-pod> → <software-name>` (env-specific runtime address) |

> **DELETE WHEN FILLING IN.** A typical Pod has one inbound
> `instantiates` row per container in the pod (most often one
> for the main app container), exactly one `runs` row pointing at
> the software part it hosts, and exactly one `binding` row
> recording the runtime address. The `binding` row's owner is the
> pod, not the underlying container — pick whichever runtime kind
> actually owns the address in your topology.

## Notes

Anything not captured above — node placement quirks, sidecar
configuration drift, persistent volume mounts, secret handling,
CPU/memory request/limit tuning history.
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
        "subtype IN ('software', 'container', 'image', 'pod')",
    )

    # ---------- Phase 2: extend templates.kind allow-list ----------
    op.execute(
        "ALTER TABLE templates DROP CONSTRAINT ck_templates_kind_allowed"
    )
    op.create_check_constraint(
        "kind_allowed",
        "templates",
        "kind IN ('software', 'container', 'image', 'pod', "
        "'interaction', 'binding', 'connection')",
    )

    # ---------- Phase 3: seed the pod template at v1.0.0 active ----------
    bind.execute(sa.text("INSERT INTO templates (kind) VALUES ('pod')"))
    template_id = bind.execute(
        sa.text("SELECT id FROM templates WHERE kind = 'pod'")
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
        {"template_id": template_id, "markdown": POD_TEMPLATE_V1},
    )


def downgrade() -> None:
    bind = op.get_bind()

    # Strip the pod template (versions first, then row).
    bind.execute(
        sa.text(
            "DELETE FROM template_versions WHERE template_id IN "
            "(SELECT id FROM templates WHERE kind = 'pod')"
        )
    )
    bind.execute(sa.text("DELETE FROM templates WHERE kind = 'pod'"))

    # Restore 0008's templates kind allow-list (drop 'pod').
    op.execute(
        "ALTER TABLE templates DROP CONSTRAINT ck_templates_kind_allowed"
    )
    op.create_check_constraint(
        "kind_allowed",
        "templates",
        "kind IN ('software', 'container', 'image', "
        "'interaction', 'binding', 'connection')",
    )

    # Restore 0008's parts subtype allow-list (drop 'pod'). Any pod-
    # subtype rows would fail this CHECK on a clean downgrade against
    # a DB that has such rows — that's the correct behaviour: you
    # can't downgrade past a feature whose data is still in use.
    op.execute(
        "ALTER TABLE parts DROP CONSTRAINT ck_parts_subtype_allowed"
    )
    op.create_check_constraint(
        "subtype_allowed",
        "parts",
        "subtype IN ('software', 'container', 'image')",
    )
