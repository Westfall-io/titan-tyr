from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://titan:titan@localhost:5432/titan_tyr"
    templates_dir: Path = Path(__file__).resolve().parent.parent / "templates"


@lru_cache
def get_settings() -> Settings:
    return Settings()
