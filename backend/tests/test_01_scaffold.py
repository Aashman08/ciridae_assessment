from sqlalchemy import text

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


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_migrations_create_our_twelve_tables(session):
    rows = session.execute(
        text(
            "select table_schema, table_name from information_schema.tables "
            "where table_schema in ('raw', 'recon') and table_name <> 'alembic_version'"
        )
    ).all()
    assert {tuple(r) for r in rows} == OUR_TABLES


def test_source_export_is_in_its_own_database(session, source):
    assert source.execute(text("select count(*) from source_company.projects")).scalar() == 25
    ours = session.execute(text("select count(*) from information_schema.schemata where schema_name = 'source_company'")).scalar()
    assert ours == 0


def test_source_connection_is_read_only():
    import pytest
    from sqlalchemy.exc import DBAPIError

    from app.db import get_source_engine

    with get_source_engine().connect() as connection, pytest.raises(DBAPIError, match="read-only"):
        connection.execute(text("update source_company.projects set notes = 'x'"))
