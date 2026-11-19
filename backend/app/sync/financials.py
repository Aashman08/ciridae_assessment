"""Step 3 of a sync: total each job's money lines.

Revenue and cost each come in three figures, because the three systems do
not agree and nothing in the data says which is right. The totals are stored
separately; a profit figure is only ever computed for a chosen pair.
"""

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Job, JobFinancials, MoneyLine, SyncRun

ZERO = Decimal(0)


class RevenueBasis(StrEnum):
    ledger = "ledger"  # booked as earned by finance
    invoiced = "invoiced"  # every invoice raised, sent or not
    collected = "collected"  # cash received


class CostBasis(StrEnum):
    ops_log = "ops_log"  # entered by the project team
    ledger = "ledger"  # booked by finance
    ledger_plus_unpaid_bills = "ledger_plus_unpaid_bills"  # upper bound


REVENUE_LABELS = {
    RevenueBasis.ledger: ("Earned, per ledger", "Revenue finance has booked for this job"),
    RevenueBasis.invoiced: ("Invoiced", "Every invoice raised, sent or not"),
    RevenueBasis.collected: ("Collected", "Cash received from the customer"),
}
COST_LABELS = {
    CostBasis.ops_log: ("Ops log", "Costs the project team entered"),
    CostBasis.ledger: ("Ledger", "Costs finance has booked"),
    CostBasis.ledger_plus_unpaid_bills: (
        "Ledger + unpaid bills",
        "Highest it could be. Some bills may already be in the ledger",
    ),
}


def revenue_for(fin: JobFinancials, basis: RevenueBasis) -> Decimal:
    return {
        RevenueBasis.ledger: fin.ledger_revenue,
        RevenueBasis.invoiced: fin.invoiced,
        RevenueBasis.collected: fin.collected,
    }[basis]


def cost_for(fin: JobFinancials, basis: CostBasis) -> Decimal:
    return {
        CostBasis.ops_log: fin.ops_cost,
        CostBasis.ledger: fin.ledger_cost,
        CostBasis.ledger_plus_unpaid_bills: fin.ledger_cost + fin.unpaid_bills,
    }[basis]


def margin_pct(revenue: Decimal, cost: Decimal) -> Decimal | None:
    """Profit as a share of revenue, to one decimal. None when there is no revenue."""
    if revenue <= 0:
        return None
    return ((revenue - cost) / revenue * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def profit(fin: JobFinancials, revenue_basis: RevenueBasis, cost_basis: CostBasis) -> dict:
    revenue, cost = revenue_for(fin, revenue_basis), cost_for(fin, cost_basis)
    return {
        "revenue_basis": revenue_basis,
        "cost_basis": cost_basis,
        "revenue": revenue,
        "cost": cost,
        "profit": revenue - cost,
        "margin_pct": margin_pct(revenue, cost),
    }


def compute_financials(session: Session, run: SyncRun) -> dict:
    lines_by_job: dict[int, list[MoneyLine]] = defaultdict(list)
    for line in session.scalars(select(MoneyLine).where(MoneyLine.job_id.is_not(None))):
        lines_by_job[line.job_id].append(line)

    jobs = session.scalars(select(Job)).all()
    for job in jobs:
        lines = lines_by_job.get(job.id, [])

        def total(kind: str) -> Decimal:
            return sum((l.amount for l in lines if l.kind == kind), ZERO)

        invoices = [l for l in lines if l.kind == "customer_invoice"]
        bills = [l for l in lines if l.kind == "vendor_bill"]
        invoiced = sum((i.amount for i in invoices), ZERO)
        collected = sum((i.paid_amount for i in invoices), ZERO)

        session.add(
            JobFinancials(
                job_id=job.id,
                sync_run_id=run.id,
                contract_value=job.contract_value,
                budget=job.budget,
                ops_cost=total("ops_cost"),
                ledger_cost=total("ledger_cost"),
                unpaid_bills=sum((b.amount - b.paid_amount for b in bills), ZERO),
                ledger_revenue=total("ledger_revenue"),
                invoiced=invoiced,
                sent=sum((i.amount for i in invoices if i.status == "SENT"), ZERO),
                collected=collected,
                owed=invoiced - collected,
                past_due=sum(
                    (
                        i.amount - i.paid_amount
                        for i in invoices
                        if i.status == "SENT" and i.amount > i.paid_amount and i.due_date and i.due_date < run.as_of
                    ),
                    ZERO,
                ),
            )
        )
    session.flush()
    return {"jobs": len(jobs)}


def latest_run_id(session: Session) -> int | None:
    """The most recent sync that finished. Readers always use this one."""
    return session.scalar(
        select(SyncRun.id).where(SyncRun.status == "succeeded").order_by(SyncRun.id.desc()).limit(1)
    )
