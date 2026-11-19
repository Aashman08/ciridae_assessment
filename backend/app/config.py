from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from the environment or a local .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Our own database. Everything this service writes goes here.
    database_url: str = "postgresql+psycopg:///harborstone_recon"
    # Harborstone's database, holding the export of its three systems.
    # This service only ever reads from it.
    source_database_url: str = "postgresql+psycopg:///harborstone"
    source_schema: str = "source_company"
    # When set, every API request must send it in the X-API-Key header.
    api_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
