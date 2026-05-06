"""Server-side bootstrap CLI (#81 + #84).

Today: one subcommand, `issue-token`. Run on the API host (it
connects directly to Postgres via `Settings.database_url`) to mint
the first admin token at first deploy, before the
`POST /auth-tokens` API endpoint is reachable for any caller.

Usage:

    python -m src.cli issue-token \\
        --actor chris.cox@westfall.io \\
        --description "founder admin token" \\
        --scopes revoke-agent

Plaintext is printed to stdout exactly once. Save it. The hash is
all that's stored in the DB; if you lose the plaintext, revoke the
row and issue a new one.

After bootstrap, prefer the `POST /auth-tokens` endpoint (and the
`/issue-auth-token` skill that wraps it) — the CLI exists for the
narrow case "I have shell on the API host but no working API
token yet."
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime

from sqlalchemy import insert

from src.auth_tokens import mint_token
from src.db import get_engine
from src.models import AuthToken
from src.schemas import AUTH_TOKEN_SCOPES


async def _issue_token(
    *,
    actor: str,
    description: str,
    scopes: list[str],
    expires_at: datetime | None,
    issued_by_actor: str | None,
) -> str:
    plaintext, token_hash, prefix = mint_token()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            insert(AuthToken).values(
                token_hash=token_hash,
                token_prefix=prefix,
                actor=actor,
                description=description,
                scopes=sorted(set(scopes)),
                issued_by_actor=issued_by_actor,
                expires_at=expires_at,
            )
        )
    return plaintext


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="src.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser(
        "issue-token",
        help="Mint a new auth token. Plaintext printed once to stdout.",
    )
    p.add_argument("--actor", required=True, help="X-Actor identity this token speaks as")
    p.add_argument(
        "--description",
        required=True,
        help='One-line "what is this token" (1-200 chars)',
    )
    p.add_argument(
        "--scopes",
        required=True,
        help=(
            "Comma-separated scopes from "
            f"{list(AUTH_TOKEN_SCOPES)}. "
            "revoke-agent implies write implies read."
        ),
    )
    p.add_argument(
        "--expires-at",
        default=None,
        help="ISO8601 expiry (e.g. 2026-12-31T23:59:59Z). Omit for no expiry.",
    )
    p.add_argument(
        "--issued-by",
        default="bootstrap-cli",
        help="Recorded as issued_by_actor on the row. Defaults to 'bootstrap-cli'.",
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    if args.cmd != "issue-token":
        # argparse already enforces required=True so unreachable in
        # practice; defensive return rather than raise.
        return 2

    scopes = [s.strip() for s in args.scopes.split(",") if s.strip()]
    bad = [s for s in scopes if s not in AUTH_TOKEN_SCOPES]
    if bad:
        print(
            f"error: unknown scope(s) {bad}; allowed {list(AUTH_TOKEN_SCOPES)}",
            file=sys.stderr,
        )
        return 2

    expires_at = None
    if args.expires_at is not None:
        try:
            expires_at = datetime.fromisoformat(args.expires_at.replace("Z", "+00:00"))
        except ValueError as exc:
            print(f"error: --expires-at not parseable as ISO8601: {exc}", file=sys.stderr)
            return 2

    plaintext = asyncio.run(
        _issue_token(
            actor=args.actor,
            description=args.description,
            scopes=scopes,
            expires_at=expires_at,
            issued_by_actor=args.issued_by,
        )
    )

    # Output format: human-readable header + the plaintext on a line
    # by itself so a caller can pipe `... | tail -1` to extract it
    # for scripted handoff into a secret store.
    print("=" * 60, file=sys.stderr)
    print("Auth token issued. Save the plaintext below NOW —", file=sys.stderr)
    print("it will not be shown again. Hash + prefix only are", file=sys.stderr)
    print("stored in the database.", file=sys.stderr)
    print(f"  actor:       {args.actor}", file=sys.stderr)
    print(f"  description: {args.description}", file=sys.stderr)
    print(f"  scopes:      {sorted(set(scopes))}", file=sys.stderr)
    print(f"  expires_at:  {expires_at}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(plaintext)  # stdout: just the plaintext
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
