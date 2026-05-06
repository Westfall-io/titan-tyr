"""Env-var driven CORS allow-list, per #15.

Two layers of coverage:
- `resolve_cors_config` unit tests — pure function over an env dict.
- One integration check that the wired-in middleware honors the env at
  app creation. (Behavioral coverage of the default + non-default
  paths is in tests/test_cors.py via the regular `client` fixture.)
"""
from __future__ import annotations

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from src import db as db_module
from src.cors import (
    DEFAULT_ALLOW_ORIGIN_REGEX,
    InvalidCorsOrigin,
    resolve_cors_config,
)
from src.main import create_app
from tests.conftest import PASSWORD


# ---------- resolve_cors_config (pure unit) ----------


class TestResolveDefault:
    def test_unset_env_falls_back_to_default_regex(self):
        cfg = resolve_cors_config(env={})
        assert cfg.allow_origins is None
        assert cfg.allow_origin_regex == DEFAULT_ALLOW_ORIGIN_REGEX

    def test_empty_env_var_falls_back_to_default_regex(self):
        cfg = resolve_cors_config(env={"CORS_ALLOWED_ORIGINS": ""})
        assert cfg.allow_origin_regex == DEFAULT_ALLOW_ORIGIN_REGEX

    def test_whitespace_only_env_var_falls_back_to_default(self):
        cfg = resolve_cors_config(env={"CORS_ALLOWED_ORIGINS": "   "})
        assert cfg.allow_origin_regex == DEFAULT_ALLOW_ORIGIN_REGEX


class TestResolveExplicitList:
    def test_single_origin(self):
        cfg = resolve_cors_config(
            env={"CORS_ALLOWED_ORIGINS": "https://watchervault.example.com"}
        )
        assert cfg.allow_origins == ["https://watchervault.example.com"]
        assert cfg.allow_origin_regex is None

    def test_multiple_origins_comma_separated(self):
        cfg = resolve_cors_config(
            env={
                "CORS_ALLOWED_ORIGINS": (
                    "https://watchervault.example.com,"
                    "https://other-tenant.example.com,"
                    "http://localhost:8765"
                )
            }
        )
        assert cfg.allow_origins == [
            "https://watchervault.example.com",
            "https://other-tenant.example.com",
            "http://localhost:8765",
        ]

    def test_whitespace_around_commas_trimmed(self):
        cfg = resolve_cors_config(
            env={"CORS_ALLOWED_ORIGINS": " https://a.com , https://b.com  "}
        )
        assert cfg.allow_origins == ["https://a.com", "https://b.com"]

    def test_empty_entries_skipped(self):
        cfg = resolve_cors_config(
            env={"CORS_ALLOWED_ORIGINS": "https://a.com,,,https://b.com,"}
        )
        assert cfg.allow_origins == ["https://a.com", "https://b.com"]

    def test_only_empty_entries_falls_back_to_default(self):
        cfg = resolve_cors_config(env={"CORS_ALLOWED_ORIGINS": ",,,"})
        assert cfg.allow_origin_regex == DEFAULT_ALLOW_ORIGIN_REGEX
        assert cfg.allow_origins is None


class TestResolveAllowAny:
    def test_allow_any_origin_true(self):
        cfg = resolve_cors_config(env={"CORS_ALLOW_ANY_ORIGIN": "true"})
        assert cfg.allow_origins == ["*"]
        assert cfg.allow_origin_regex is None

    def test_allow_any_origin_case_insensitive(self):
        cfg = resolve_cors_config(env={"CORS_ALLOW_ANY_ORIGIN": "TRUE"})
        assert cfg.allow_origins == ["*"]

    def test_allow_any_origin_with_whitespace(self):
        cfg = resolve_cors_config(env={"CORS_ALLOW_ANY_ORIGIN": "  true  "})
        assert cfg.allow_origins == ["*"]

    def test_allow_any_origin_false_falls_back(self):
        cfg = resolve_cors_config(env={"CORS_ALLOW_ANY_ORIGIN": "false"})
        assert cfg.allow_origin_regex == DEFAULT_ALLOW_ORIGIN_REGEX

    def test_allow_any_origin_empty_falls_back(self):
        cfg = resolve_cors_config(env={"CORS_ALLOW_ANY_ORIGIN": ""})
        assert cfg.allow_origin_regex == DEFAULT_ALLOW_ORIGIN_REGEX

    def test_allow_any_origin_takes_precedence_over_explicit_list(self):
        cfg = resolve_cors_config(
            env={
                "CORS_ALLOW_ANY_ORIGIN": "true",
                "CORS_ALLOWED_ORIGINS": "https://a.com",
            }
        )
        assert cfg.allow_origins == ["*"]


class TestValidationFailFast:
    def test_star_in_explicit_list_rejected(self):
        with pytest.raises(InvalidCorsOrigin, match="does not accept '\\*'"):
            resolve_cors_config(env={"CORS_ALLOWED_ORIGINS": "*"})

    def test_star_alongside_real_origins_rejected(self):
        with pytest.raises(InvalidCorsOrigin, match="does not accept '\\*'"):
            resolve_cors_config(
                env={"CORS_ALLOWED_ORIGINS": "https://a.com,*,https://b.com"}
            )

    def test_wildcard_subdomain_rejected(self):
        with pytest.raises(InvalidCorsOrigin, match="wildcards are out of scope"):
            resolve_cors_config(
                env={"CORS_ALLOWED_ORIGINS": "https://*.example.com"}
            )

    def test_unsupported_scheme_rejected(self):
        with pytest.raises(InvalidCorsOrigin, match="scheme must be http or https"):
            resolve_cors_config(env={"CORS_ALLOWED_ORIGINS": "ftp://example.com"})

    def test_missing_scheme_rejected(self):
        with pytest.raises(InvalidCorsOrigin):
            resolve_cors_config(env={"CORS_ALLOWED_ORIGINS": "example.com"})

    def test_missing_host_rejected(self):
        with pytest.raises(InvalidCorsOrigin, match="missing host"):
            resolve_cors_config(env={"CORS_ALLOWED_ORIGINS": "https://"})

    def test_trailing_slash_rejected(self):
        with pytest.raises(InvalidCorsOrigin, match="bare origin"):
            resolve_cors_config(
                env={"CORS_ALLOWED_ORIGINS": "https://example.com/"}
            )

    def test_path_rejected(self):
        with pytest.raises(InvalidCorsOrigin, match="bare origin"):
            resolve_cors_config(
                env={"CORS_ALLOWED_ORIGINS": "https://example.com/api"}
            )

    def test_query_rejected(self):
        with pytest.raises(InvalidCorsOrigin, match="bare origin"):
            resolve_cors_config(
                env={"CORS_ALLOWED_ORIGINS": "https://example.com?foo=bar"}
            )


# ---------- integration: env actually wires through to the middleware ----------


async def _client_with_env(monkeypatch, engine, db_session, env: dict[str, str]):
    """Build a client whose app was constructed with the given CORS env."""
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session():
        async with sessionmaker() as session:
            yield session

    app = create_app()
    app.dependency_overrides[db_module.get_session] = override_session
    return app, override_session


class TestIntegration:
    async def test_explicit_list_blocks_default_digitalforge(
        self, monkeypatch, engine, db_session
    ):
        # When CORS_ALLOWED_ORIGINS is set, the default regex no longer
        # applies — digitalforge.app should NOT be allowed automatically.
        app, _ = await _client_with_env(
            monkeypatch,
            engine,
            db_session,
            {"CORS_ALLOWED_ORIGINS": "https://watchervault.example.com"},
        )
        async with LifespanManager(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                ac.headers.update({"Authorization": f"Bearer {PASSWORD}"})

                # Configured origin → allowed
                r = await ac.get(
                    "/parts",
                    headers={"Origin": "https://watchervault.example.com"},
                )
                assert r.status_code == 200
                assert (
                    r.headers.get("access-control-allow-origin")
                    == "https://watchervault.example.com"
                )

                # Default-regex origin → no longer allowed because env replaced the list
                r = await ac.get(
                    "/parts", headers={"Origin": "https://digitalforge.app"}
                )
                assert r.status_code == 200
                assert "access-control-allow-origin" not in r.headers

    async def test_allow_any_origin_echoes_anything(
        self, monkeypatch, engine, db_session
    ):
        app, _ = await _client_with_env(
            monkeypatch, engine, db_session, {"CORS_ALLOW_ANY_ORIGIN": "true"}
        )
        async with LifespanManager(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                ac.headers.update({"Authorization": f"Bearer {PASSWORD}"})
                r = await ac.get(
                    "/parts", headers={"Origin": "https://evil.com"}
                )
                assert r.status_code == 200
                assert r.headers.get("access-control-allow-origin") == "*"

    async def test_invalid_env_var_raises_at_create_app(self, monkeypatch):
        monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://example.com,*")
        with pytest.raises(InvalidCorsOrigin):
            create_app()
