"""Test setup.

Tests use two databases of their own, rebuilt once per test session:
`harborstone_test` is a copy of Harborstone's export, and `harborstone_recon_test`
is ours. The working `harborstone` and `harborstone_recon` databases are never touched.
"""

import os
import subprocess
from pathlib import Path

import pytest

TEST_DB = "harborstone_recon_test"
TEST_SOURCE_DB = "harborstone_test"
REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"
DUMP = REPO_ROOT / "source_data.sql"

os.environ["DATABASE_URL"] = f"postgresql+psycopg:///{TEST_DB}"
os.environ["SOURCE_DATABASE_URL"] = f"postgresql+psycopg:///{TEST_SOURCE_DB}"
os.environ.pop("API_KEY", None)


def _run(*cmd: str) -> None:
    subprocess.run(cmd, check=True, capture_output=True, cwd=BACKEND)


@pytest.fixture(scope="session", autouse=True)
def database():
    from app.db import reset_caches

    reset_caches()
    for name in (TEST_DB, TEST_SOURCE_DB):
        _run("dropdb", "--if-exists", name)
        _run("createdb", name)
    # The dump was written by a newer pg_dump, which adds \restrict lines that
    # older psql versions reject. They are not needed for a restore.
    sql = "\n".join(
        line for line in DUMP.read_text().splitlines() if not line.startswith(("\\restrict", "\\unrestrict"))
    )
    subprocess.run(
        ["psql", "-q", "-X", "-v", "ON_ERROR_STOP=1", "-d", TEST_SOURCE_DB],
        input=sql, text=True, check=True, capture_output=True,
    )
    _run("uv", "run", "alembic", "upgrade", "head")
    yield
    reset_caches()


@pytest.fixture
def session(database):
    from app.db import new_session

    s = new_session()
    yield s
    s.close()


@pytest.fixture
def source(database):
    """A writable session on the test copy of Harborstone's database, so a
    test can change the source and check that a sync picks it up."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    engine = create_engine(os.environ["SOURCE_DATABASE_URL"])
    with Session(engine) as s:
        yield s
    engine.dispose()


@pytest.fixture
def client(database):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
