"""Sync step 3: per-job totals, and profit for a chosen revenue and cost pair."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import event, func, select

from app.core import database
from app.sync.financials import CostBasis, RevenueBasis, latest_run_id, margin_pct, profit
from app.core.models import Job, JobFinancials

pytestmark = pytest.mark.usefixtures("synced")
D = Decimal


async def fin(db, job_number) -> JobFinancials:
    return await db.scalar(
        select(JobFinancials)
        .join(Job, Job.id == JobFinancials.job_id)
        .where(Job.job_number == job_number, JobFinancials.sync_run_id == await latest_run_id(db))
    )


async def total(db, column, run_id=None) -> Decimal:
    run_id = run_id or await latest_run_id(db)
    return await db.scalar(select(func.sum(column)).where(JobFinancials.sync_run_id == run_id))


async def test_one_row_per_job_per_run(db):
    run_id = await latest_run_id(db)
    count = await db.scalar(
        select(func.count()).select_from(JobFinancials).where(JobFinancials.sync_run_id == run_id)
    )
    assert count == 25


async def test_job_totals_match_the_source(db):
    f = await fin(db, "CTX00080002")
    assert (f.contract_value, f.budget) == (D("664300.00"), D("455000.00"))
    assert (f.ops_cost, f.ledger_cost, f.unpaid_bills) == (D("327600.00"), D("318500.00"), D("76680.00"))
    assert (f.ledger_revenue, f.invoiced, f.sent, f.collected) == (
        D("432500.00"), D("324800.00"), D("216500.00"), D("129900.00"),
    )
    assert (f.owed, f.past_due) == (D("194900.00"), D("86600.00"))


async def test_company_totals(db):
    assert await total(db, JobFinancials.owed) == D("1477564.00")
    assert await total(db, JobFinancials.past_due) == D("719004.00")
    assert await total(db, JobFinancials.invoiced) == D("3174100.00")
    assert await total(db, JobFinancials.collected) == D("1696536.00")
    # 423,215 of vendor bills, less 8,985 on three bills that have no job.
    assert await total(db, JobFinancials.unpaid_bills) == D("414230.00")


async def test_profit_depends_on_the_pair_chosen(db):
    f = await fin(db, "CTX00080002")
    ledger = profit(f, RevenueBasis.ledger, CostBasis.ledger)
    assert (ledger["revenue"], ledger["cost"], ledger["profit"]) == (D("432500.00"), D("318500.00"), D("114000.00"))
    assert ledger["margin_pct"] == D("26.4")
    assert profit(f, RevenueBasis.ledger, CostBasis.ops_log)["profit"] == D("104900.00")
    cash = profit(f, RevenueBasis.collected, CostBasis.ledger_plus_unpaid_bills)
    assert (cash["cost"], cash["profit"]) == (D("395180.00"), D("-265280.00"))


async def test_closed_job_margin_drops_when_unpaid_bills_are_counted(db):
    f = await fin(db, "RTX00010004")
    assert profit(f, RevenueBasis.ledger, CostBasis.ledger)["margin_pct"] == D("30.0")
    assert profit(f, RevenueBasis.ledger, CostBasis.ledger_plus_unpaid_bills)["margin_pct"] == D("14.2")


async def test_no_margin_without_revenue(db):
    result = profit(await fin(db, "CTX00150002"), RevenueBasis.ledger, CostBasis.ops_log)
    assert (result["revenue"], result["profit"], result["margin_pct"]) == (0, D("-188240.00"), None)


def test_margin_rounds_half_up():
    assert margin_pct(D("1000"), D("735.5")) == D("26.5")  # 26.45 rounds up
    assert margin_pct(D("0"), D("10")) is None


async def test_past_due_follows_the_as_of_date(recon, db):
    early = await recon.run_sync(as_of=date(2026, 7, 1))
    assert await total(db, JobFinancials.past_due, early.id) == 0
    late = await recon.run_sync(as_of=date(2026, 8, 30))
    # Everything sent and unpaid: 1,477,564 owed less 369,100 never sent.
    assert await total(db, JobFinancials.past_due, late.id) == D("1108464.00")


async def test_sync_does_its_totals_and_checks_in_the_database(recon):
    """Totals are one INSERT ... SELECT ... GROUP BY, and each check is a filtered query."""
    statements: list[str] = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(" ".join(statement.split()))

    event.listen(database.engine.sync_engine, "before_cursor_execute", capture)
    try:
        run = await recon.run_sync()
    finally:
        event.remove(database.engine.sync_engine, "before_cursor_execute", capture)

    totals = [s for s in statements if s.startswith("INSERT INTO recon.job_financials")]
    assert len(totals) == 1
    assert "SELECT recon.job.id" in totals[0] and "GROUP BY recon.job.id" in totals[0]
    assert run.stats["financials"]["jobs"] == 25

    # The past-due check asks only for late, unpaid, sent invoices.
    assert any("recon.money_line.due_date <" in s and "recon.money_line.status =" in s for s in statements)
    # Nothing during totals or checks reads the whole money_line table.
    whole_table = [s for s in statements if s.startswith("SELECT") and "FROM recon.money_line" in s and "WHERE" not in s]
    assert whole_table == []
