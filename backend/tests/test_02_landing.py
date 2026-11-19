"""Sync step 1: source rows are copied untouched, and only when they change."""

from datetime import date

import pytest
from sqlalchemy import func, select, text

from app.client import create_recon_client
from app.connector import SYSTEM_BY_TABLE
from app.landing import content_hash
from app.models import SourceRecord, SyncRun


async def source_row_count(source) -> int:
    tables = await source.scalars(
        text("select table_name from information_schema.tables where table_schema = 'source_company'")
    )
    return sum([await source.scalar(text(f'select count(*) from source_company."{t}"')) for t in tables])


async def test_first_sync_copies_every_source_row(recon, db, source):
    run = await recon.run_sync()
    stats = run.stats["land"]
    assert run.status == "succeeded"
    assert stats["tables"] == 42
    assert stats["rows"] == stats["new"] == await source_row_count(source)
    assert await db.scalar(select(func.count()).select_from(SourceRecord)) == stats["rows"]


async def test_as_of_defaults_to_the_export_date(recon):
    assert (await recon.run_sync()).as_of == date(2026, 7, 28)


async def test_every_table_is_assigned_to_a_system(db):
    rows = await db.execute(select(SourceRecord.table_name, SourceRecord.system).distinct())
    systems = dict(rows.all())
    assert set(systems) == set(SYSTEM_BY_TABLE)
    assert "unknown" not in systems.values()


async def test_copied_row_matches_its_source(db, source):
    row = (
        await source.execute(
            text("select id, total from source_company.ar_invoices where invoice_number = 'INV-2026-0538'")
        )
    ).one()
    copied = await db.scalar(
        select(SourceRecord).where(SourceRecord.table_name == "ar_invoices", SourceRecord.source_pk == str(row.id))
    )
    assert copied.system == "accounting"
    assert copied.payload["invoice_number"] == "INV-2026-0538"
    assert float(copied.payload["total"]) == float(row.total) == 246300.0
    assert copied.content_hash == content_hash(copied.payload)


async def test_second_sync_with_no_changes_rewrites_nothing(recon, db):
    first = await recon.run_sync()
    second = await recon.run_sync()
    stats = second.stats["land"]
    assert (stats["new"], stats["changed"]) == (0, 0)
    assert stats["unchanged"] == stats["rows"]
    rewritten = await db.scalar(
        select(func.count()).select_from(SourceRecord).where(SourceRecord.last_changed_run_id > first.id)
    )
    not_seen = await db.scalar(
        select(func.count()).select_from(SourceRecord).where(SourceRecord.last_seen_run_id != second.id)
    )
    assert (rewritten, not_seen) == (0, 0)


async def test_changed_source_row_is_picked_up(recon, source):
    await recon.run_sync()
    await source.execute(text("update source_company.project_notes set content = content || ' (edited)'"))
    await source.commit()
    try:
        stats = (await recon.run_sync()).stats["land"]
        assert (stats["changed"], stats["new"]) == (3, 0)
    finally:
        await source.execute(
            text("update source_company.project_notes set content = replace(content, ' (edited)', '')")
        )
        await source.commit()
        await recon.run_sync()


async def test_sync_leaves_nothing_behind_in_the_source_database(recon, source):
    await recon.run_sync()
    schemas = (await source.scalars(text("select schema_name from information_schema.schemata"))).all()
    assert "raw" not in schemas and "recon" not in schemas


async def test_failed_sync_keeps_nothing_but_the_failure(db):
    class BrokenConnector:
        async def tables(self):
            return ["projects"]

        async def rows(self, table):
            raise RuntimeError("source system unreachable")

        async def metadata(self, key):
            return "2026-07-28"

    before = await db.scalar(select(func.count()).select_from(SourceRecord))
    with pytest.raises(RuntimeError, match="unreachable"):
        async with create_recon_client("test", connector=BrokenConnector()) as client:
            await client.run_sync()

    run = await db.scalar(select(SyncRun).order_by(SyncRun.id.desc()).limit(1))
    assert run.status == "failed"
    assert run.error == "RuntimeError: source system unreachable"
    assert await db.scalar(select(func.count()).select_from(SourceRecord)) == before
