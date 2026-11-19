from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models import Job, JobFinancials
from app.sync.financials import CostBasis, RevenueBasis, latest_run_id, profit
from app.sync.runner import run_sync

D = Decimal


@pytest.fixture(scope="module", autouse=True)
def synced(database):
    from app.db import new_session

    with new_session() as s:
        run_sync(s)


def fin(session, job_number, run_id=None) -> JobFinancials:
    return session.scalar(
        select(JobFinancials)
        .join(Job, Job.id == JobFinancials.job_id)
        .where(Job.job_number == job_number, JobFinancials.sync_run_id == (run_id or latest_run_id(session)))
    )


def total(session, column, run_id=None):
    return session.scalar(select(func.sum(column)).where(JobFinancials.sync_run_id == (run_id or latest_run_id(session))))


def test_one_row_per_job_per_run(session):
    run_id = latest_run_id(session)
    count = session.scalar(select(func.count()).select_from(JobFinancials).where(JobFinancials.sync_run_id == run_id))
    assert count == 25


def test_job_totals_match_the_source(session):
    f = fin(session, "CTX00080002")
    assert f.contract_value == D("664300.00")
    assert f.budget == D("455000.00")
    assert (f.ops_cost, f.ledger_cost, f.unpaid_bills) == (D("327600.00"), D("318500.00"), D("76680.00"))
    assert (f.ledger_revenue, f.invoiced, f.sent, f.collected) == (
        D("432500.00"), D("324800.00"), D("216500.00"), D("129900.00"),
    )
    assert (f.owed, f.past_due) == (D("194900.00"), D("86600.00"))


def test_company_totals(session):
    assert total(session, JobFinancials.owed) == D("1477564.00")
    assert total(session, JobFinancials.past_due) == D("719004.00")
    assert total(session, JobFinancials.invoiced) == D("3174100.00")
    assert total(session, JobFinancials.collected) == D("1696536.00")
    # 423,215 of vendor bills, less 8,985 on three bills that have no job.
    assert total(session, JobFinancials.unpaid_bills) == D("414230.00")


def test_profit_depends_on_the_pair_chosen(session):
    f = fin(session, "CTX00080002")
    ledger = profit(f, RevenueBasis.ledger, CostBasis.ledger)
    assert (ledger["revenue"], ledger["cost"], ledger["profit"]) == (D("432500.00"), D("318500.00"), D("114000.00"))
    assert ledger["margin_pct"] == D("26.4")

    ops = profit(f, RevenueBasis.ledger, CostBasis.ops_log)
    assert ops["profit"] == D("104900.00")

    cash = profit(f, RevenueBasis.collected, CostBasis.ledger_plus_unpaid_bills)
    assert cash["cost"] == D("395180.00")
    assert cash["profit"] == D("-265280.00")


def test_closed_job_margin_drops_when_unpaid_bills_are_counted(session):
    f = fin(session, "RTX00010004")
    assert profit(f, RevenueBasis.ledger, CostBasis.ledger)["margin_pct"] == D("30.0")
    assert profit(f, RevenueBasis.ledger, CostBasis.ledger_plus_unpaid_bills)["margin_pct"] == D("14.2")


def test_no_margin_without_revenue(session):
    f = fin(session, "CTX00150002")
    result = profit(f, RevenueBasis.ledger, CostBasis.ops_log)
    assert result["revenue"] == 0
    assert result["profit"] == D("-188240.00")
    assert result["margin_pct"] is None


def test_past_due_follows_the_as_of_date(session):
    early = run_sync(session, as_of=date(2026, 7, 1))
    assert total(session, JobFinancials.past_due, early.id) == 0
    late = run_sync(session, as_of=date(2026, 8, 30))
    # Everything sent and unpaid: 1,477,564 owed less 369,100 never sent.
    assert total(session, JobFinancials.past_due, late.id) == D("1108464.00")
    run_sync(session)
