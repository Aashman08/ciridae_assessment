"""Sync step 2: jobs, companies, owners and money lines built from the copied rows."""

from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import selectinload

from app.core.models import Company, CostCodeMap, Job, JobOwner, MoneyLine, SourceRecord

pytestmark = pytest.mark.usefixtures("synced")
D = Decimal


async def line_total(db, kind) -> Decimal:
    return await db.scalar(select(func.coalesce(func.sum(MoneyLine.amount), 0)).where(MoneyLine.kind == kind))


async def test_one_job_per_project(db):
    assert await db.scalar(select(func.count()).select_from(Job)) == 25


async def test_companies_keep_customer_and_vendor_flags(db):
    customers = await db.scalar(select(func.count()).select_from(Company).where(Company.is_customer))
    vendors = await db.scalar(select(func.count()).select_from(Company).where(Company.is_vendor))
    assert (customers, vendors) == (16, 10)
    alliance = await db.scalar(select(Company).where(Company.name == "Alliance Roofing Supply"))
    assert alliance.vendor_ref == "V10318"
    assert (alliance.discount_pct, alliance.discount_days) == (D("2.00"), 10)


async def test_job_joins_crm_project_and_budget(db):
    job = await db.scalar(
        select(Job)
        .where(Job.job_number == "CTX00080002")
        .options(selectinload(Job.owners), selectinload(Job.customer))
    )
    assert job.name == "Redbird — Building A Dock Rebuild"
    assert job.customer.name == "Redbird Industrial Trust"
    assert (job.branch, job.stage, job.crm_status) == ("Dallas", "IN_PROGRESS", "WON")
    assert job.contract_value == D("664300.00")
    # The one change order in the export raised this contract.
    assert job.original_contract_value == D("618700.00")
    assert (job.budget, job.planned_margin_pct) == (D("455000.00"), D("26.00"))
    assert {o.role: o.name for o in job.owners} == {
        "account_executive": "Marcus Webb",
        "ops_manager": "Ray Delgado",
    }


async def test_seven_jobs_have_no_ops_manager(db):
    with_ops = select(JobOwner.job_id).where(JobOwner.role == "ops_manager")
    missing = (await db.scalars(select(Job.job_number).where(Job.id.not_in(with_ops)))).all()
    assert len(missing) == 7
    assert "BTX00030002" in missing


async def test_money_line_counts_by_kind(db):
    rows = await db.execute(select(MoneyLine.kind, func.count()).group_by(MoneyLine.kind))
    assert dict(rows.all()) == {
        "ops_cost": 51,
        "ledger_cost": 34,
        "ledger_revenue": 34,
        "ledger_receivable": 16,
        "ledger_receipt": 10,
        "vendor_bill": 18,
        "customer_invoice": 21,
        "customer_payment": 10,
    }


async def test_totals_tie_to_the_source(db, source):
    assert await line_total(db, "customer_invoice") == D("3174100.00")
    assert await line_total(db, "customer_payment") == D("1696536.00")
    assert await line_total(db, "vendor_bill") == D("423215.00")
    assert await line_total(db, "ops_cost") == await source.scalar(
        text("select sum(amount) from source_company.actual_costs")
    )
    ledger = "select sum(amount) from source_company.gl_entries where source_object = 'GLDETAIL' and account_no like "
    assert await line_total(db, "ledger_cost") == await source.scalar(text(ledger + "'5%'"))
    assert await line_total(db, "ledger_revenue") == await source.scalar(text(ledger + "'4%'"))


async def test_invoice_carries_what_has_been_paid(db):
    invoice = await db.scalar(
        select(MoneyLine)
        .where(MoneyLine.doc_number == "INV-2026-0502", MoneyLine.kind == "customer_invoice")
        .options(selectinload(MoneyLine.job), selectinload(MoneyLine.company))
    )
    assert (invoice.amount, invoice.paid_amount) == (D("216500.00"), D("129900.00"))
    assert invoice.job.job_number == "CTX00080002"
    assert invoice.company.name == "Redbird Industrial Trust"


async def test_three_vendor_bills_have_no_job(db):
    orphans = await db.scalars(
        select(MoneyLine.doc_number).where(MoneyLine.kind == "vendor_bill", MoneyLine.job_id.is_(None))
    )
    assert sorted(orphans) == ["DTL-10012", "DTL-9954", "MDC-55201"]


async def test_every_money_line_traces_to_its_source_row(db):
    rows = (
        await db.execute(
            select(MoneyLine, SourceRecord).join(SourceRecord, SourceRecord.id == MoneyLine.source_record_id)
        )
    ).all()
    assert len(rows) == await db.scalar(select(func.count()).select_from(MoneyLine)) == 194
    for line, record in rows:
        assert (record.table_name, record.source_pk) == (line.source_table, line.source_pk)
    bill, record = next((l, r) for l, r in rows if l.doc_number == "ARS-20447")
    assert record.payload["invoice_number"] == "ARS-20447"
    assert D(str(record.payload["amount"])) == bill.amount


async def test_cost_codes_from_both_systems_map_to_one_category(db):
    rows = await db.execute(select(CostCodeMap.source_system, CostCodeMap.source_code, CostCodeMap.category))
    lookup = {(system, code): category for system, code, category in rows}
    assert lookup[("accounting", "internal-labor")] == lookup[("project", "INTERNAL_LABOR")] == "INTERNAL_LABOR"
    assert lookup[("ledger", "5020")] == "UNCLASSIFIED"


async def test_resync_keeps_ids_and_removes_nothing(recon, db):
    jobs_before = dict((await db.execute(select(Job.job_number, Job.id))).all())
    lines_before = dict((await db.execute(select(MoneyLine.source_pk, MoneyLine.id))).all())
    run = await recon.run_sync()
    assert run.stats["normalize"]["removed"] == 0
    assert dict((await db.execute(select(Job.job_number, Job.id))).all()) == jobs_before
    assert dict((await db.execute(select(MoneyLine.source_pk, MoneyLine.id))).all()) == lines_before
