"""The two databases, their separation, and service-level behaviour."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app import database

OUR_TABLES = {
    ("raw", "source_record"),
    ("recon", "sync_run"),
    ("recon", "company"),
    ("recon", "job"),
    ("recon", "job_owner"),
    ("recon", "cost_code_map"),
    ("recon", "money_line"),
    ("recon", "job_financials"),
    ("recon", "issue_type"),
    ("recon", "issue"),
    ("recon", "issue_evidence"),
    ("recon", "issue_event"),
}


async def test_migrations_create_our_twelve_tables(db):
    rows = await db.execute(
        text(
            "select table_schema, table_name from information_schema.tables "
            "where table_schema in ('raw', 'recon') and table_name <> 'alembic_version'"
        )
    )
    assert {tuple(r) for r in rows} == OUR_TABLES


async def test_migrations_are_tracked(db):
    version = await db.scalar(text("select version_num from recon.alembic_version"))
    assert version


async def test_export_lives_in_a_separate_database(db, source):
    assert await source.scalar(text("select count(*) from source_company.projects")) == 25
    in_ours = await db.scalar(
        text("select count(*) from information_schema.schemata where schema_name = 'source_company'")
    )
    assert in_ours == 0


async def test_source_connection_is_read_only():
    async with database.source_engine.connect() as connection:
        with pytest.raises(DBAPIError, match="read-only"):
            await connection.execute(text("update source_company.projects set notes = 'x'"))


async def test_health(api):
    response = await api.get("/health")
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"]


async def test_reads_before_any_sync_say_so(api):
    response = await api.get("/api/v1/jobs")
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["type"] == "invalid_state"
    assert "No sync has finished yet" in error["message"]
    assert error["request_id"] == response.headers["X-Request-ID"]
