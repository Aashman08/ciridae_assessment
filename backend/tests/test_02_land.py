from datetime import date

from sqlalchemy import func, select, text

from app.models import SourceRecord
from app.sync.connector import SYSTEM_BY_TABLE
from app.sync.land import content_hash
from app.sync.runner import run_sync


def source_row_count(source) -> int:
    tables = source.execute(
        text("select table_name from information_schema.tables where table_schema = 'source_company'")
    ).scalars()
    return sum(source.execute(text(f'select count(*) from source_company."{t}"')).scalar() for t in tables)


def test_first_sync_lands_every_source_row(session, source):
    run = run_sync(session)
    stats = run.stats["land"]
    assert run.status == "succeeded"
    assert stats["tables"] == 42
    assert stats["rows"] == source_row_count(source)
    assert session.scalar(select(func.count()).select_from(SourceRecord)) == stats["rows"]


def test_as_of_defaults_to_the_export_date(session):
    assert run_sync(session).as_of == date(2026, 7, 28)


def test_every_table_is_assigned_to_a_system(session):
    systems = dict(session.execute(select(SourceRecord.table_name, SourceRecord.system).distinct()).all())
    assert set(systems) == set(SYSTEM_BY_TABLE)
    assert "unknown" not in systems.values()


def test_landed_row_matches_its_source(session, source):
    run_sync(session)
    row = source.execute(
        text("select id, invoice_number, total from source_company.ar_invoices where invoice_number = 'INV-2026-0538'")
    ).one()
    landed = session.scalar(
        select(SourceRecord).where(SourceRecord.table_name == "ar_invoices", SourceRecord.source_pk == str(row.id))
    )
    assert landed.system == "accounting"
    assert landed.payload["invoice_number"] == "INV-2026-0538"
    assert float(landed.payload["total"]) == float(row.total) == 246300.0
    assert landed.content_hash == content_hash(landed.payload)


def test_second_sync_with_no_changes_rewrites_nothing(session):
    first = run_sync(session)
    second = run_sync(session)
    stats = second.stats["land"]
    assert stats["new"] == 0
    assert stats["changed"] == 0
    assert stats["unchanged"] == stats["rows"]
    # Nothing was re-landed, and every row was seen again.
    changed_in_second = session.scalar(
        select(func.count()).select_from(SourceRecord).where(SourceRecord.last_changed_run_id > first.id)
    )
    not_seen = session.scalar(
        select(func.count()).select_from(SourceRecord).where(SourceRecord.last_seen_run_id != second.id)
    )
    assert changed_in_second == 0
    assert not_seen == 0


def test_a_changed_source_row_is_picked_up(session, source):
    run_sync(session)
    source.execute(text("update source_company.project_notes set content = content || ' (edited)' where true"))
    source.commit()
    try:
        stats = run_sync(session).stats["land"]
        assert stats["changed"] == 3
        assert stats["new"] == 0
    finally:
        source.execute(
            text("update source_company.project_notes set content = replace(content, ' (edited)', '') where true")
        )
        source.commit()
        run_sync(session)


def test_sync_leaves_nothing_behind_in_the_source_database(session, source):
    run_sync(session)
    schemas = source.execute(text("select schema_name from information_schema.schemata")).scalars().all()
    assert "raw" not in schemas and "recon" not in schemas
