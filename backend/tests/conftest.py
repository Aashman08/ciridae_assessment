"""Shared fixtures.

Tests use two databases of their own, rebuilt once per test session:
`harborstone_test` is a copy of Harborstone's export and
`harborstone_recon_test` is ours. The working databases are never touched.

Each test module starts with our tables empty, so one module's syncs and
issue changes cannot leak into the next.
"""

import os
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path

RECON_DB = "harborstone_recon_test"
SOURCE_DB = "harborstone_test"
os.environ["DATABASE_URL"] = f"postgresql+psycopg:///{RECON_DB}"
os.environ["SOURCE_DATABASE_URL"] = f"postgresql+psycopg:///{SOURCE_DB}"
os.environ.pop("API_KEY", None)
# Tests never use a real model key, even when backend/.env has one. An empty
# value here overrides the file, so no test can reach the network or spend money.
os.environ["OPENAI_API_KEY"] = ""
os.environ["ASK_MODEL"] = ""
# Tests start their own syncs. A scheduled one would change the data under them.
os.environ["SYNC_EVERY_MINUTES"] = "0"

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402

from app import database  # noqa: E402
from app.client import ReconClient, create_recon_client  # noqa: E402
from app.schemas import SyncRunResponse  # noqa: E402
from app.server import app  # noqa: E402

DUMP = Path(__file__).resolve().parents[2] / "source_data.sql"
OUR_TABLES = (
    "raw.source_record, recon.sync_run, recon.company, recon.job, recon.job_owner, "
    "recon.cost_code_map, recon.money_line, recon.job_financials, recon.issue_type, "
    "recon.issue, recon.issue_evidence, recon.issue_event, recon.ask_exchange, recon.job_review"
)


@pytest.fixture(scope="session", autouse=True)
def databases() -> None:
    """Build both test databases from scratch and migrate ours."""
    for name in (RECON_DB, SOURCE_DB):
        subprocess.run(["dropdb", "--if-exists", name], check=True, capture_output=True)
        subprocess.run(["createdb", name], check=True, capture_output=True)
    # The dump was written by a newer pg_dump, which adds \restrict lines that
    # older psql versions reject. They are not needed for a restore.
    sql = "\n".join(
        line for line in DUMP.read_text().splitlines() if not line.startswith(("\\restrict", "\\unrestrict"))
    )
    subprocess.run(
        ["psql", "-q", "-X", "-v", "ON_ERROR_STOP=1", "-d", SOURCE_DB],
        input=sql, text=True, check=True, capture_output=True,
    )
    database.migrate_database()


@pytest_asyncio.fixture(scope="module", autouse=True)
async def empty_database(databases) -> None:
    """Start every test module with our tables empty."""
    async with database.engine.begin() as connection:
        await connection.execute(text(f"truncate {OUR_TABLES} restart identity cascade"))


@pytest_asyncio.fixture(scope="module")
async def synced(empty_database) -> SyncRunResponse:
    """One sync of the export, shared by the tests in a module."""
    async with create_recon_client("test-setup") as client:
        return await client.run_sync()


@pytest_asyncio.fixture
async def recon() -> AsyncIterator[ReconClient]:
    """The client the endpoints use, for calling operations directly."""
    async with create_recon_client("test") as client:
        yield client


@pytest_asyncio.fixture
async def db() -> AsyncIterator[AsyncSession]:
    """A session on our database for direct assertions."""
    async with database.SessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def source() -> AsyncIterator[AsyncSession]:
    """A writable session on the test copy of Harborstone's database, so a
    test can change the source and check that a sync picks it up."""
    engine = create_async_engine(os.environ["SOURCE_DATABASE_URL"])
    async with AsyncSession(engine) as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def api() -> AsyncIterator[httpx.AsyncClient]:
    """An HTTP client wired straight to the application."""
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
