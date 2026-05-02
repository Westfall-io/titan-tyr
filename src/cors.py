"""CORS allow-list resolution.

Resolves the CORS configuration the API should serve, in this precedence:

1. ``CORS_ALLOW_ANY_ORIGIN=true`` → fully open (``allow_origins=["*"]``).
   Opt-in only; never the default. Use only for short-lived testing.
2. ``CORS_ALLOWED_ORIGINS`` set and non-empty → comma-separated list of
   literal origins replaces the source-hardcoded default.
3. Neither set → fall back to the source-hardcoded regex
   (``digitalforge.app`` + subdomains over HTTPS, ``localhost`` on any
   port over HTTP/HTTPS).

Invalid entries in ``CORS_ALLOWED_ORIGINS`` raise ``InvalidCorsOrigin``
at startup so misconfiguration fails fast instead of silently dropping
origins the operator expected to be allowed.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

DEFAULT_ALLOW_ORIGIN_REGEX = (
    r"^https://(.*\.)?digitalforge\.app$"
    r"|^https?://localhost(:\d+)?$"
)


class InvalidCorsOrigin(ValueError):
    """Raised when CORS_ALLOWED_ORIGINS contains an entry we won't accept."""


@dataclass(frozen=True)
class CorsConfig:
    """The fields a CORSMiddleware needs.

    Exactly one of ``allow_origins`` / ``allow_origin_regex`` carries the
    decision; the other is ``None``.
    """

    allow_origins: list[str] | None
    allow_origin_regex: str | None


def _validate_origin(origin: str) -> str:
    """Validate one CORS_ALLOWED_ORIGINS entry. Returns the trimmed origin.

    Rejects ``*``, paths, trailing slashes, and unsupported schemes.
    Wildcard subdomains (e.g. ``https://*.example.com``) are out of scope
    for this env var; use the source-hardcoded regex for those cases.
    """
    if origin == "*":
        raise InvalidCorsOrigin(
            "CORS_ALLOWED_ORIGINS does not accept '*'. "
            "Set CORS_ALLOW_ANY_ORIGIN=true to opt into fully-open CORS."
        )
    parsed = urlparse(origin)
    if parsed.scheme not in ("http", "https"):
        raise InvalidCorsOrigin(
            f"CORS_ALLOWED_ORIGINS entry {origin!r}: scheme must be http or https"
        )
    if not parsed.hostname:
        raise InvalidCorsOrigin(
            f"CORS_ALLOWED_ORIGINS entry {origin!r}: missing host"
        )
    if parsed.path or parsed.params or parsed.query or parsed.fragment:
        raise InvalidCorsOrigin(
            f"CORS_ALLOWED_ORIGINS entry {origin!r}: must be a bare origin "
            "(scheme://host[:port]) — no path, no trailing slash, no query"
        )
    if "*" in origin:
        raise InvalidCorsOrigin(
            f"CORS_ALLOWED_ORIGINS entry {origin!r}: wildcards are out of scope; "
            "use literal origins only"
        )
    return origin


def resolve_cors_config(env: dict[str, str] | None = None) -> CorsConfig:
    """Resolve CORS configuration from environment variables."""
    e = env if env is not None else os.environ

    if e.get("CORS_ALLOW_ANY_ORIGIN", "").strip().lower() == "true":
        return CorsConfig(allow_origins=["*"], allow_origin_regex=None)

    raw = e.get("CORS_ALLOWED_ORIGINS", "").strip()
    if raw:
        origins = [s.strip() for s in raw.split(",") if s.strip()]
        if origins:
            validated = [_validate_origin(o) for o in origins]
            return CorsConfig(allow_origins=validated, allow_origin_regex=None)

    return CorsConfig(allow_origins=None, allow_origin_regex=DEFAULT_ALLOW_ORIGIN_REGEX)
