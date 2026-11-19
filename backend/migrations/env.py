from alembic import context
from sqlalchemy import text

from app.db import get_engine
from app.models import RAW, RECON, Base

target_metadata = Base.metadata


def include_name(name, type_, parent_names):
    # Only manage our own schemas. The source export is never touched.
    if type_ == "schema":
        return name in (RAW, RECON)
    return True


def run_migrations_online() -> None:
    with get_engine().connect() as connection:
        connection.execute(text(f"create schema if not exists {RAW}"))
        connection.execute(text(f"create schema if not exists {RECON}"))
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_name=include_name,
            version_table_schema=RECON,
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
