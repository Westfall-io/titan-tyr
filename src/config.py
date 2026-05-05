from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://titan:titan@localhost:5432/titan_tyr"

    # Identities that the human-confirmation rule (#76) treats as
    # agents. The acceptor X-Actor on a destructive accept (today:
    # part deletion) must NOT be one of these — two agents bouncing
    # the handshake back and forth otherwise satisfies the
    # two-party rule without a human ever confirming a wipe-and-
    # cascade. Override per-environment with
    # `KNOWN_AGENT_ACTORS=foo,bar` (comma-separated).
    known_agent_actors: frozenset[str] = frozenset({"titan-tyr", "titan-archaedas"})

    @classmethod
    def parse_env_var(cls, field_name: str, raw_val: str):
        # pydantic-settings doesn't natively split a CSV env var into
        # a frozenset[str] — handle it explicitly so the operator can
        # set `KNOWN_AGENT_ACTORS=foo,bar` rather than a JSON literal.
        if field_name == "known_agent_actors":
            return frozenset(
                tok.strip() for tok in raw_val.split(",") if tok.strip()
            )
        return raw_val


@lru_cache
def get_settings() -> Settings:
    return Settings()
