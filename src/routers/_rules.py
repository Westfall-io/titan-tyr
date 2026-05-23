"""Per-subtype validation rules shared across the parts and contracts routers.

These constants describe what shape of (owner, counterparty) is valid
for each contract subtype / connection_type label. They live here
(rather than inside `contracts.py`) so the subtype-shift impact
preview in `parts.py` can consult them without creating a circular
import — `contracts.py` already imports from `parts.py`.

Pair-level rule table (#101): each `connection_type` maps to an
explicit list of `(owner_subtype, counterparty_subtype)` pairs.
Lax-union expression (separate `owner` and `counterparty` sets) can't
express directional pairs cleanly under the K8s chain — `composes`
needs `compose -> container` distinct from `deployment -> pod` distinct
from `pod -> container`, and a union-based encoding admits invalid
cross-pairs like `compose -> pod`. Pair-level rules are the canonical
shape; helper functions below derive owner/counterparty sets when a
caller needs them.
"""
from __future__ import annotations

# Binding contracts express the runtime address at which a software
# part is reachable. Originally container-only; extended to pod in
# #36 (the SysMLv2 binding spec was always permissive — `pod` just
# didn't exist as a Part subtype yet).
BINDING_OWNER_SUBTYPES: tuple[str, ...] = ("container", "pod")

# Per-label (owner_subtype, counterparty_subtype) pair rules for
# `connection`-subtype contracts. Order within each label's list is not
# semantically meaningful but is kept stable for deterministic error
# messages.
CONNECTION_RULES: dict[str, list[tuple[str, str]]] = {
    "builds-from": [
        ("software", "image"),
    ],
    "instantiates": [
        ("image", "container"),
        ("image", "pod"),
    ],
    "runs": [
        ("container", "software"),
        ("pod", "software"),
    ],
    # `composes` (#101) replaces `member-of`. Direction is top-down:
    # parent spec -> child it contains. The K8s chain reads
    # `deployment / statefulset / job -> pod -> container`, plus
    # `chart -composes-> <K8s primitive>` (#100) at the top of the
    # umbrella stack, plus the existing `compose -composes-> container`
    # for the Docker-compose side.
    "composes": [
        # Compose-side umbrella (formerly `container -member-of-> compose`).
        ("compose", "container"),
        # K8s controllers compose pods.
        ("deployment", "pod"),
        ("statefulset", "pod"),
        ("job", "pod"),
        # Pod composes container specs (multi-container pods / sidecars
        # become expressible).
        ("pod", "container"),
        # Helm release umbrella (#100). Note: `chart -composes-> pod` is
        # intentionally not in the pair list — pods are owned by their
        # controllers (deployment / statefulset / job) and reached
        # transitively. Mirrors `compose -composes-> container` not
        # `compose -composes-> pod`.
        ("chart", "deployment"),
        ("chart", "statefulset"),
        ("chart", "job"),
        ("chart", "service"),
        ("chart", "ingress"),
        ("chart", "secret"),
        ("chart", "configmap"),
    ],
    "depends-on": [
        ("container", "container"),
    ],
    "submodule": [
        ("software", "software"),
    ],
    "serves-static": [
        ("software", "software"),
    ],
    # K8s runtime contract labels added in #92 (archaedas#9).
    "selects": [
        ("service", "deployment"),
        ("service", "statefulset"),
    ],
    "routes-to": [
        ("ingress", "service"),
    ],
    # All 6 (secret | configmap) -> (deployment | statefulset | job)
    # pairs are admitted. The narrower real-world set (e.g. whether
    # configmap-into-job actually shows up) is left as policy in
    # template bodies; the rules table enforces shape, not policy.
    "consumed-by": [
        ("secret", "deployment"),
        ("secret", "statefulset"),
        ("secret", "job"),
        ("configmap", "deployment"),
        ("configmap", "statefulset"),
        ("configmap", "job"),
    ],
}


def allowed_owner_subtypes(connection_type: str) -> set[str]:
    """Set of owner subtypes admitted for this `connection_type`.

    Derived from the pair list. Use for individual-subtype error
    messages and impact-preview narrowing.
    """
    return {p[0] for p in CONNECTION_RULES[connection_type]}


def allowed_counterparty_subtypes(connection_type: str) -> set[str]:
    """Set of counterparty subtypes admitted for this `connection_type`."""
    return {p[1] for p in CONNECTION_RULES[connection_type]}


def is_pair_allowed(
    connection_type: str, owner_subtype: str, counterparty_subtype: str
) -> bool:
    """True if `(owner_subtype, counterparty_subtype)` is a valid pair.

    Pair-level check. Catches "both subtypes individually admitted but
    not together" cases (the main reason for the union → pair refactor).
    """
    return (owner_subtype, counterparty_subtype) in CONNECTION_RULES[connection_type]


def format_allowed_pairs(connection_type: str) -> str:
    """Human-readable list of valid pairs for error messages.

    Returns e.g. ``"compose -> container, deployment -> pod, ..."``.
    """
    return ", ".join(
        f"{o} -> {c}" for o, c in CONNECTION_RULES[connection_type]
    )
