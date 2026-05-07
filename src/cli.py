"""Server-side bootstrap CLI (#81 + #84) and Kubernetes init-container
helper (#89).

Two subcommands today:

- `issue-token` — first-deploy bootstrap. Connects directly to Postgres
  via `Settings.database_url` to insert an `auth_tokens` row before
  the API has any working bearer to authenticate with. Plaintext
  printed exactly once.

- `k8s-init-token` — Kubernetes init-container helper. Reads an admin
  bearer from a mounted Secret, issues (or reuses) a per-caller token
  via the API, patches a K8s Secret with the new plaintext, and hands
  off to the main container via a shared file. Uses **only** the
  Kubernetes API and the titan-tyr API — no DB access — so the same
  titan-tyr image can serve as both the API and the init container
  with different `command:` values, instead of needing a separate
  init image with curl/kubectl on top of an alpine base.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime

from sqlalchemy import insert

from src.auth_tokens import mint_token
from src.db import get_engine
from src.models import AuthToken
from src.schemas import AUTH_TOKEN_SCOPES


# ---------- issue-token (DB-direct bootstrap) ----------


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


def _cmd_issue_token(args: argparse.Namespace) -> int:
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

    print("=" * 60, file=sys.stderr)
    print("Auth token issued. Save the plaintext below NOW —", file=sys.stderr)
    print("it will not be shown again. Hash + prefix only are", file=sys.stderr)
    print("stored in the database.", file=sys.stderr)
    print(f"  actor:       {args.actor}", file=sys.stderr)
    print(f"  description: {args.description}", file=sys.stderr)
    print(f"  scopes:      {sorted(set(scopes))}", file=sys.stderr)
    print(f"  expires_at:  {expires_at}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(plaintext)
    return 0


# ---------- k8s-init-token (init-container helper) ----------
#
# Standard pod-mount paths that the K8s API server populates on every
# pod via the default ServiceAccount-token projected volume. Reading
# the bearer from the file (not env) keeps it out of `ps` output.
_SA_TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"
_SA_CA_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
_K8S_API = "https://kubernetes.default.svc"


def _read_file_or_none(path: str) -> str | None:
    try:
        with open(path) as f:
            content = f.read().strip()
    except FileNotFoundError:
        return None
    return content or None


def _http_request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    ca_path: str | None = None,
) -> tuple[int, bytes]:
    """Tiny urllib wrapper. Returns (status, body) on any HTTP outcome
    (2xx or HTTPError); raises only on transport-level failures.
    """
    req = urllib.request.Request(url, method=method, data=data)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    context = None
    if ca_path is not None:
        context = ssl.create_default_context(cafile=ca_path)
    try:
        with urllib.request.urlopen(req, context=context) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _probe(api_url: str, token: str) -> bool:
    """True iff `token` authenticates against the live titan-tyr API."""
    status, _ = _http_request(
        f"{api_url.rstrip('/')}/parts?limit=1",
        headers={"Authorization": f"Bearer {token}"},
    )
    return status == 200


def _issue_via_api(
    api_url: str,
    admin_token: str,
    *,
    actor: str,
    description: str,
    scopes: list[str],
    expires_at: str | None,
) -> str:
    """POST /auth-tokens; return the freshly minted plaintext."""
    body: dict = {
        "actor": actor,
        "description": description,
        "scopes": scopes,
    }
    if expires_at:
        body["expires_at"] = expires_at
    status, response = _http_request(
        f"{api_url.rstrip('/')}/auth-tokens",
        method="POST",
        headers={
            "Authorization": f"Bearer {admin_token}",
            "Content-Type": "application/json",
        },
        data=json.dumps(body).encode("utf-8"),
    )
    if status != 201:
        raise RuntimeError(
            f"issue-token failed: HTTP {status} {response.decode('utf-8', 'replace')}"
        )
    return json.loads(response)["token"]


def _patch_k8s_secret(
    namespace: str,
    secret_name: str,
    key: str,
    plaintext: str,
) -> None:
    """Strategic-merge patch the named Secret with `key=plaintext`.

    Uses the pod's ServiceAccount-mounted bearer + CA. The ServiceAccount
    must have `patch` on this specific Secret (scope via resourceNames
    in a Role; do NOT grant cluster-wide secrets:patch).
    """
    sa_token = _read_file_or_none(_SA_TOKEN_PATH)
    if not sa_token:
        raise RuntimeError(
            f"ServiceAccount token not found at {_SA_TOKEN_PATH} — "
            "is this running inside a Pod with automountServiceAccountToken?"
        )
    encoded = base64.b64encode(plaintext.encode("utf-8")).decode("ascii")
    body = json.dumps({"data": {key: encoded}}).encode("utf-8")
    url = f"{_K8S_API}/api/v1/namespaces/{namespace}/secrets/{secret_name}"
    status, response = _http_request(
        url,
        method="PATCH",
        headers={
            "Authorization": f"Bearer {sa_token}",
            "Content-Type": "application/strategic-merge-patch+json",
        },
        data=body,
        ca_path=_SA_CA_PATH,
    )
    if status not in (200, 201):
        raise RuntimeError(
            f"K8s Secret patch failed: HTTP {status} "
            f"{response.decode('utf-8', 'replace')}"
        )


def _cmd_k8s_init_token(args: argparse.Namespace) -> int:
    api_url = os.environ.get("TITAN_TYR_URL")
    if not api_url:
        print("error: TITAN_TYR_URL is not set", file=sys.stderr)
        return 2
    namespace = os.environ.get("POD_NAMESPACE")
    if not namespace:
        print(
            "error: POD_NAMESPACE is not set (use the K8s downward API)",
            file=sys.stderr,
        )
        return 2

    scopes = [s.strip() for s in args.scopes.split(",") if s.strip()]
    bad = [s for s in scopes if s not in AUTH_TOKEN_SCOPES]
    if bad:
        print(
            f"error: unknown scope(s) {bad}; allowed {list(AUTH_TOKEN_SCOPES)}",
            file=sys.stderr,
        )
        return 2

    # Step 1: try to reuse an existing live token from the UI Secret mount.
    existing = _read_file_or_none(args.existing_token_file)
    if existing and _probe(api_url, existing):
        print("[init] existing token is live; reusing.", file=sys.stderr)
        # Contract with mimiron's nginx/12-load-handoff-token.sh
        # (titan-mimiron#58): file holds the plaintext only, no trailing
        # newline or whitespace. `_read_file_or_none` strips on read; we
        # write back unmodified.
        os.makedirs(os.path.dirname(args.handoff_file) or ".", exist_ok=True)
        with open(args.handoff_file, "w") as f:
            f.write(existing)
        return 0

    if existing:
        print(
            "[init] existing token failed probe (expired/revoked?); rotating.",
            file=sys.stderr,
        )

    # Step 2: issue a fresh token via the admin bearer.
    admin = _read_file_or_none(args.admin_token_file)
    if not admin:
        print(
            f"error: admin token file {args.admin_token_file} is empty or missing.\n"
            "Devops must seed the admin Secret from a server-side\n"
            "`python -m src.cli issue-token` run.",
            file=sys.stderr,
        )
        return 2

    plaintext = _issue_via_api(
        api_url,
        admin,
        actor=args.actor,
        description=args.description,
        scopes=scopes,
        expires_at=args.expires_at,
    )

    # Step 3: persist into the K8s Secret so future pod starts can reuse.
    _patch_k8s_secret(namespace, args.ui_secret, "TITAN_TYR_TOKEN", plaintext)

    # Step 4: hand off to the main container via the shared emptyDir.
    # Contract with mimiron's nginx/12-load-handoff-token.sh
    # (titan-mimiron#58): file holds the plaintext only, no trailing
    # newline or whitespace. `secrets.token_urlsafe` produces no
    # whitespace and `f.write(plaintext)` adds none — keep it that way.
    os.makedirs(os.path.dirname(args.handoff_file) or ".", exist_ok=True)
    with open(args.handoff_file, "w") as f:
        f.write(plaintext)

    print(
        f"[init] new token issued + persisted to Secret {args.ui_secret}.",
        file=sys.stderr,
    )
    return 0


# ---------- argparse wiring ----------


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="src.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser(
        "issue-token",
        help="Mint a new auth token via DB insert (bootstrap path).",
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

    k = sub.add_parser(
        "k8s-init-token",
        help=(
            "Kubernetes init-container helper: reuse-or-issue a per-caller "
            "token via the API and patch a K8s Secret. Uses the same image "
            "as the API; expects TITAN_TYR_URL + POD_NAMESPACE in env, plus "
            "a ServiceAccount with patch permission on the named Secret."
        ),
    )
    k.add_argument("--actor", required=True)
    k.add_argument("--description", required=True)
    k.add_argument(
        "--scopes",
        required=True,
        help=f"Comma-separated scopes from {list(AUTH_TOKEN_SCOPES)}",
    )
    k.add_argument(
        "--ui-secret",
        required=True,
        help="K8s Secret name to read/write the token (must exist in POD_NAMESPACE)",
    )
    k.add_argument(
        "--admin-token-file",
        default="/admin/TITAN_TYR_TOKEN",
        help="Path to the admin bearer file (default /admin/TITAN_TYR_TOKEN)",
    )
    k.add_argument(
        "--existing-token-file",
        default="/ui-secret/TITAN_TYR_TOKEN",
        help=(
            "Path to the existing UI token mount (default "
            "/ui-secret/TITAN_TYR_TOKEN). May be missing on first deploy."
        ),
    )
    k.add_argument(
        "--handoff-file",
        default="/handoff/TITAN_TYR_TOKEN",
        help="Path to write the live token for the main container",
    )
    k.add_argument(
        "--expires-at",
        default=None,
        help="ISO8601 expiry to set on newly issued tokens (optional).",
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    if args.cmd == "issue-token":
        return _cmd_issue_token(args)
    if args.cmd == "k8s-init-token":
        return _cmd_k8s_init_token(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
