from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


@lru_cache
def get_engine() -> Engine:
    # A fixed session timezone keeps timestamps in landed rows identical from
    # run to run, so content hashes only change when the source data does.
    return create_engine(
        get_settings().database_url,
        connect_args={"options": "-c timezone=UTC"},
        pool_pre_ping=True,
    )


@lru_cache
def get_source_engine() -> Engine:
    """Harborstone's database, opened read-only so a bug here cannot change it."""
    return create_engine(
        get_settings().source_database_url,
        connect_args={"options": "-c timezone=UTC -c default_transaction_read_only=on"},
        pool_pre_ping=True,
    )


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def new_session() -> Session:
    return _session_factory()()


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    session = new_session()
    try:
        yield session
    finally:
        session.close()


def reset_caches() -> None:
    """Drop cached settings and engine. Used by tests that switch databases."""
    for cached in (get_engine, get_source_engine):
        if cached.cache_info().currsize:
            cached().dispose()
        cached.cache_clear()
    _session_factory.cache_clear()
    get_settings.cache_clear()
