"""Token generation + hashing helpers (#81 + #84).

Tokens are 32 bytes of `secrets.token_urlsafe` output (43 chars after
b64 stripping). Hash is sha256 hex; the visible prefix kept on the
row is the first 8 chars of the plaintext (non-secret).

sha256 not bcrypt/argon2: these are server-issued high-entropy
random tokens, not human-chosen passwords. The slow-by-design
property of password-grade KDFs adds per-request cost without
buying anything against an attacker holding a leaked DB.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

# 32 random bytes → ~43-char url-safe string. Enough entropy that
# offline brute-force is infeasible; short enough to fit in
# `Authorization: Bearer <token>` headers without comment.
_TOKEN_BYTES = 32

# The visible-on-list prefix that lets ops grep/identify a token
# without the plaintext. First 8 chars of the plaintext.
_PREFIX_LEN = 8


def mint_token() -> tuple[str, str, str]:
    """Mint a fresh token.

    Returns (plaintext, sha256_hex, prefix). The plaintext should be
    handed to the operator exactly once and otherwise discarded;
    only the hash and prefix are stored.
    """
    plaintext = secrets.token_urlsafe(_TOKEN_BYTES)
    return plaintext, hash_token(plaintext), plaintext[:_PREFIX_LEN]


def hash_token(plaintext: str) -> str:
    """Return the sha256 hex digest the auth dependency will look up."""
    return hashlib.sha256(plaintext.encode("ascii")).hexdigest()


def constant_time_eq(a: str, b: str) -> bool:
    """Timing-safe equality for bearer comparisons.

    Used by the legacy shared-bearer fallback path so the env-loaded
    `TITAN_TYR_BEARER_PASSWORD` comparison doesn't leak length /
    prefix information. The per-caller token path doesn't need this
    — it's a hashed-index lookup, not a string compare.
    """
    return hmac.compare_digest(a.encode("ascii"), b.encode("ascii"))
