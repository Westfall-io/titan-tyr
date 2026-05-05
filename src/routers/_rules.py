"""Per-subtype validation rules shared across the parts and contracts routers.

These constants describe what shape of (owner, counterparty) is valid
for each contract subtype / connection_type label. They live here
(rather than inside `contracts.py`) so the subtype-shift impact
preview in `parts.py` can consult them without creating a circular
import — `contracts.py` already imports from `parts.py`.
"""
from __future__ import annotations

# Binding contracts express the runtime address at which a software
# part is reachable. Originally container-only; extended to pod in
# #36 (the SysMLv2 binding spec was always permissive — `pod` just
# didn't exist as a Part subtype yet).
BINDING_OWNER_SUBTYPES: tuple[str, ...] = ("container", "pod")

# Per-label From/To Part subtype rules for connection contracts (#32).
# `owner` / `counterparty` are sets of allowed subtype strings.
CONNECTION_RULES: dict[str, dict[str, set[str]]] = {
    "builds-from":  {"owner": {"software"},          "counterparty": {"image"}},
    "instantiates": {"owner": {"image"},             "counterparty": {"container", "pod"}},
    "runs":         {"owner": {"container", "pod"},  "counterparty": {"software"}},
    "member-of":    {"owner": {"container"},         "counterparty": {"compose"}},
    "depends-on":   {"owner": {"container"},         "counterparty": {"container"}},
    "submodule":    {"owner": {"software"},          "counterparty": {"software"}},
    "serves-static":{"owner": {"software"},          "counterparty": {"software"}},
}
