from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://titan:titan@localhost:5432/titan_tyr"

    # Legacy shared-bearer password, transitional during the #81/#82/#84
    # cutover. Empty default → the legacy auth path is fail-closed; only
    # per-caller tokens (DB-backed in `auth_tokens`) are accepted.
    # A deployer staging the cutover can set
    # `TITAN_TYR_BEARER_PASSWORD=<value>` to keep their pre-cutover
    # consumers working while they migrate to per-caller tokens. Drop
    # the env var (or set to empty) once the migration is complete.
    # The validation_alias keeps the env var namespaced even though
    # the rest of the settings (database_url etc.) follow the
    # bare-name convention.
    bearer_password: str = Field(
        default="", validation_alias="TITAN_TYR_BEARER_PASSWORD"
    )

    # OIDC pass-through (#124). When `keycloak_issuer` is set, JWT-shaped
    # bearers are validated against the issuer's JWKS instead of looked
    # up in `auth_tokens`. Per-caller tokens still work unchanged. Empty
    # issuer → OIDC path is off and a JWT-shaped bearer falls through to
    # the per-caller-token DB lookup (which will 401, since hash misses).
    # See #118 for the design (3-tier model, OIDC pass-through).
    keycloak_issuer: str = Field(
        default="", validation_alias="TITAN_TYR_KEYCLOAK_ISSUER"
    )
    keycloak_audience: str = Field(
        default="", validation_alias="TITAN_TYR_KEYCLOAK_AUDIENCE"
    )
    keycloak_jwks_ttl_seconds: int = Field(
        default=3600, validation_alias="TITAN_TYR_KEYCLOAK_JWKS_TTL_SECONDS"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
