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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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


async def get_active_agent_actors(session: AsyncSession) -> frozenset[str]:
    """Return the live agent-actor allowlist from the agent_actors table (#78).

    Replaces the hardcoded `settings.known_agent_actors` config default
    that #76 shipped. Callers fetch the set per request and pass it
    into `enforce_human_confirmation` — keeps the gate function pure
    and the DB read explicit at the call site.

    Imported lazily to avoid a circular import: `models` imports
    `db.Base`, this module is imported by routers that own models.
    """
    from src.models import AgentActor

    rows = (
        await session.execute(
            select(AgentActor.actor).where(AgentActor.revoked_at.is_(None))
        )
    ).scalars().all()
    return frozenset(rows)


def enforce_human_confirmation(
    *,
    acceptor_actor: str | None,
    known_agents: frozenset[str] | set[str],
) -> None:
    """403 if the acceptor X-Actor is unset or in the known-agent allowlist.

    Stricter sibling of `enforce_two_party` for destructive flows
    (today: part deletion, #76). Two distinct agents bouncing a
    handshake back and forth satisfies the soft two-party rule but
    leaves no human in the loop — for irreversible / cascading
    operations that's not enough. The acceptor must be a human
    operator (i.e., not a known agent identity).

    The proposer is intentionally NOT checked: the typical flow is
    "agent notices something needs cleanup, human confirms." Only
    acceptance is gated.

    Edge cases:
    - acceptor_actor is None → 422 (unconfirmable, treated as
      missing-confirmation rather than agent).
    - acceptor_actor is in `known_agents` → 403.
    - acceptor_actor is anything else → allow.

    Callers should also reject `?single_operator=true` separately —
    the bypass defeats the purpose of human confirmation. This
    helper does not check the bypass flag because the helper is
    composable; the route has the right context to give a clearer
    422 message.
    """
    if acceptor_actor is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "destructive accept requires an X-Actor header on the "
                "request — null actor cannot satisfy the human-"
                "confirmation rule"
            ),
        )
    if acceptor_actor in known_agents:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"destructive accept requires a human operator — "
                f"acceptor X-Actor {acceptor_actor!r} is a known agent "
                f"(allowlist: {sorted(known_agents)}). Have a human "
                f"set X-Actor and re-run the accept."
            ),
        )


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
