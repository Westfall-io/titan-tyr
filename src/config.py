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


@lru_cache
def get_settings() -> Settings:
    return Settings()
