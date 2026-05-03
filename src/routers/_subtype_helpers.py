"""Shared helpers for the subtype-shift propose/accept flow (#33).

Both `/parts/{name}/subtype-proposals/...` and
`/contracts/{contract_id}/subtype-proposals/...` share the same
two-party acceptance handshake (X-Actor header + ?single_operator=true
override) and the same body-stamp drift computation. Extracted here
so the per-resource routers stay focused on resource-specific
validation.
"""
from __future__ import annotations

import re

from fastapi import HTTPException, status

# Stamp on the first line of every Part / Contract / Template markdown:
#   <!-- template: <kind>@<MAJOR.MINOR.PATCH(-rcN)?> -->
# Only the kind needs to be parsed to detect drift after a subtype shift;
# the version is checked elsewhere by the audit-skill flow.
_STAMP_PATTERN = re.compile(
    r"^<!--\s*template:\s*([a-z][a-z0-9-]*)@\d+\.\d+\.\d+(?:-rc\d+)?\s*-->"
)


def extract_stamp_kind(markdown: str | None) -> str | None:
    """Return the `<kind>` from the first-line template-version stamp.

    Returns None if no body, no stamp, or stamp grammar doesn't match.
    The caller decides what to do with a missing stamp (typically:
    treat as "no drift detected", since the body never had a stamp to
    drift from).
    """
    if not markdown:
        return None
    first_line = markdown.split("\n", 1)[0]
    m = _STAMP_PATTERN.match(first_line)
    return m.group(1) if m else None


def body_realign_required(markdown: str | None, new_template_kind: str) -> bool:
    """True if the body's stamp kind disagrees with the new subtype's kind.

    A shift from `software` → `container` against a body still stamped
    `software@2.4.0` returns True — the user needs to follow up with a
    content proposal that re-stamps the body to `container@<version>`
    (or fully realigns the structure). A body with no stamp returns
    False (nothing to drift from).
    """
    stamp_kind = extract_stamp_kind(markdown)
    if stamp_kind is None:
        return False
    return stamp_kind != new_template_kind


def enforce_two_party(
    *,
    proposer_actor: str | None,
    acceptor_actor: str | None,
    single_operator: bool,
) -> None:
    """422 if proposer and acceptor are the same X-Actor without override.

    The rule is structural: a structural change to a row should have
    two operators sign off. Until real per-caller auth lands, the
    X-Actor header is the lightweight signal. Solo setups override
    with `?single_operator=true`.

    Edge cases:
    - Either side missing X-Actor: cannot enforce — allow. Caller
      should surface a warning in the skill layer.
    - Both sides present and identical: 422 unless single_operator.
    - Both sides present and different: allow.
    """
    if single_operator:
        return
    if proposer_actor is None or acceptor_actor is None:
        return
    if proposer_actor == acceptor_actor:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"proposer-doesn't-accept rule: actor {proposer_actor!r} "
                f"proposed this shift and cannot also accept it. Have a "
                f"different actor accept, or pass ?single_operator=true to "
                f"override (only appropriate when one human is operating "
                f"both sides of the handshake)."
            ),
        )
