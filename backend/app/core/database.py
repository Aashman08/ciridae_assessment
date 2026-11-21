"""Database configuration and application startup.

Two databases. `engine` is ours and takes every write this service makes.
`source_engine` is Harborstone's, opened read-only so nothing here can change
their data.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[2]  # backend/, above app/core/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    source_database_url: str
    source_schema: str = "source_company"
    # When set, every /api/v1 request must send it in the X-API-Key header.
    api_key: str | None = None
    # Ask. Without a key the rest of the app works and Ask says it is not set up.
    openai_api_key: str | None = None
    # Leave empty to use the OpenAI Agents SDK's default model.
    model: str | None = None
    # How often the source systems are read. 0 turns the schedule off; a sync can
    # still be started with POST /api/v1/sync-runs.
    sync_every_minutes: int = 60


settings = Settings()

# A fixed session timezone keeps timestamps in copied rows identical from run
# to run, so a row's content hash only changes when the source data does.
engine = create_async_engine(
    settings.database_url,
    connect_args={"options": "-c timezone=UTC"},
    pool_pre_ping=True,
)
source_engine = create_async_engine(
    settings.source_database_url,
    connect_args={"options": "-c timezone=UTC -c default_transaction_read_only=on"},
    pool_pre_ping=True,
)
SessionLocal = async_sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def migrate_database() -> None:
    """Bring our database up to the latest Alembic revision.

    Alembic records each applied revision in `recon.alembic_version`, so the
    database always says which schema changes it has had.
    """
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(config, "head")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await asyncio.to_thread(migrate_database)
    try:
        yield
    finally:
        await engine.dispose()
        await source_engine.dispose()
