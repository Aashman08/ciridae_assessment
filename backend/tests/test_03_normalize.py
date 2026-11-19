from decimal import Decimal

import pytest
from sqlalchemy import func, select, text

from app.models import Company, CostCodeMap, Job, JobOwner, MoneyLine, SourceRecord
from app.sync.runner import run_sync


@pytest.fixture(scope="module", autouse=True)
def synced(database):
    from app.db import new_session

    with new_session() as s:
        run_sync(s)


def line_total(session, kind) -> Decimal:
    return session.scalar(select(func.coalesce(func.sum(MoneyLine.amount), 0)).where(MoneyLine.kind == kind))


def source_total(source, sql) -> Decimal:
    return source.execute(text(sql)).scalar()


def test_one_job_per_project(session):
    assert session.scalar(select(func.count()).select_from(Job)) == 25


def test_companies_keep_customer_and_vendor_flags(session):
    customers = session.scalar(select(func.count()).select_from(Company).where(Company.is_customer))
    vendors = session.scalar(select(func.count()).select_from(Company).where(Company.is_vendor))
    assert (customers, vendors) == (16, 10)
    alliance = session.scalar(select(Company).where(Company.name == "Alliance Roofing Supply"))
    assert alliance.vendor_ref == "V10318"
    assert (alliance.discount_pct, alliance.discount_days) == (Decimal("2.00"), 10)


def test_job_joins_crm_project_and_budget(session):
    job = session.scalar(select(Job).where(Job.job_number == "CTX00080002"))
    assert job.name == "Redbird — Building A Dock Rebuild"
    assert job.customer.name == "Redbird Industrial Trust"
    assert job.branch == "Dallas"
    assert job.stage == "IN_PROGRESS"
    assert job.crm_status == "WON"
    assert job.contract_value == Decimal("664300.00")
    # The one change order in the export raised this contract.
    assert job.original_contract_value == Decimal("618700.00")
    assert job.budget == Decimal("455000.00")
    assert job.planned_margin_pct == Decimal("26.00")
    assert {o.role: o.name for o in job.owners} == {
        "account_executive": "Marcus Webb",
        "ops_manager": "Ray Delgado",
    }


def test_seven_jobs_have_no_ops_manager(session):
    with_ops = select(JobOwner.job_id).where(JobOwner.role == "ops_manager")
    missing = session.scalars(select(Job.job_number).where(Job.id.not_in(with_ops))).all()
    assert len(missing) == 7
    assert "BTX00030002" in missing


def test_money_line_counts_by_kind(session):
    counts = dict(session.execute(select(MoneyLine.kind, func.count()).group_by(MoneyLine.kind)).all())
    assert counts == {
        "ops_cost": 51,
        "ledger_cost": 34,
        "ledger_revenue": 34,
        "ledger_receivable": 16,
        "ledger_receipt": 10,
        "vendor_bill": 18,
        "customer_invoice": 21,
        "customer_payment": 10,
    }


def test_totals_tie_to_the_source(session, source):
    assert line_total(session, "customer_invoice") == Decimal("3174100.00")
    assert line_total(session, "customer_payment") == Decimal("1696536.00")
    assert line_total(session, "vendor_bill") == Decimal("423215.00")
    assert line_total(session, "ops_cost") == source_total(source, "select sum(amount) from source_company.actual_costs")
    assert line_total(session, "ledger_cost") == source_total(
        source, "select sum(amount) from source_company.gl_entries where source_object = 'GLDETAIL' and account_no like '5%'"
    )
    assert line_total(session, "ledger_revenue") == source_total(
        source, "select sum(amount) from source_company.gl_entries where source_object = 'GLDETAIL' and account_no like '4%'"
    )


def test_invoice_carries_what_has_been_paid(session):
    invoice = session.scalar(select(MoneyLine).where(MoneyLine.doc_number == "INV-2026-0502", MoneyLine.kind == "customer_invoice"))
    assert (invoice.amount, invoice.paid_amount) == (Decimal("216500.00"), Decimal("129900.00"))
    assert invoice.job.job_number == "CTX00080002"
    assert invoice.company.name == "Redbird Industrial Trust"


def test_three_vendor_bills_have_no_job(session):
    orphans = session.scalars(
        select(MoneyLine.doc_number).where(MoneyLine.kind == "vendor_bill", MoneyLine.job_id.is_(None))
    ).all()
    assert sorted(orphans) == ["DTL-10012", "DTL-9954", "MDC-55201"]


def test_every_money_line_traces_to_its_source_row(session):
    rows = session.execute(
        select(MoneyLine, SourceRecord).join(SourceRecord, SourceRecord.id == MoneyLine.source_record_id)
    ).all()
    assert len(rows) == session.scalar(select(func.count()).select_from(MoneyLine))
    for line, record in rows:
        assert record.table_name == line.source_table
        assert record.source_pk == line.source_pk
    bill, record = next((l, r) for l, r in rows if l.doc_number == "ARS-20447")
    assert record.payload["invoice_number"] == "ARS-20447"
    assert Decimal(str(record.payload["amount"])) == bill.amount


def test_cost_codes_from_both_systems_map_to_one_category(session):
    rows = session.execute(select(CostCodeMap.source_system, CostCodeMap.source_code, CostCodeMap.category)).all()
    lookup = {(system, code): category for system, code, category in rows}
    assert lookup[("accounting", "internal-labor")] == lookup[("project", "INTERNAL_LABOR")] == "INTERNAL_LABOR"
    assert lookup[("ledger", "5020")] == "UNCLASSIFIED"


def test_resync_keeps_ids_and_adds_nothing(session):
    before = dict(session.execute(select(Job.job_number, Job.id)).all())
    lines_before = dict(session.execute(select(MoneyLine.source_pk, MoneyLine.id)).all())
    run = run_sync(session)
    assert run.stats["normalize"]["removed"] == 0
    assert dict(session.execute(select(Job.job_number, Job.id)).all()) == before
    assert dict(session.execute(select(MoneyLine.source_pk, MoneyLine.id)).all()) == lines_before
