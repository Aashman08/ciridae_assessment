"""Sync step 3: total each job's money lines.

Revenue and cost each come in three figures, because the three systems do
not agree and nothing in the data says which is right. The totals are stored
separately; a profit figure is only ever computed for a chosen pair.
"""

from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from sqlalchemy import and_, func, insert, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

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


def share_pct(part: Decimal, whole: Decimal) -> Decimal:
    """A part as a share of its whole, to one decimal. Zero when the whole is nothing."""
    if whole <= 0:
        return ZERO
    return (part / whole * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def margin_pct(revenue: Decimal, cost: Decimal) -> Decimal | None:
    """Profit as a share of revenue, to one decimal. None when there is no revenue."""
    if revenue <= 0:
        return None
    return ((revenue - cost) / revenue * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def contract_stages(contract: Decimal, earned: Decimal, invoiced: Decimal, sent: Decimal, collected: Decimal) -> list[dict]:
    """Where the contract value sits on its way to cash, as parts that add up to the whole.

    Each part is the money that has reached one stage and not the next. Earned and
    invoiced can run ahead of each other, so that pair is measured against whichever is larger.
    """
    parts = [
        ("collected", collected),
        ("sent_not_collected", sent - collected),
        ("invoiced_not_sent", invoiced - sent),
        ("earned_not_invoiced", earned - invoiced),
        ("not_yet_earned", contract - max(earned, invoiced)),
    ]
    return [
        {
            "key": key,
            "amount": max(amount, ZERO),
            "share_pct": (max(amount, ZERO) / contract * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP) if contract > 0 else ZERO,
        }
        for key, amount in parts
    ]


def ledger_profit(fin: JobFinancials) -> dict:
    """The one profit figure a list of jobs shows: what finance has booked as earned,
    less what finance has booked as cost. Opening a job offers the other pairs."""
    return profit(fin, RevenueBasis.ledger, CostBasis.ledger)


# The same two figures as SQL, so a list of jobs can be sorted by them in the database.
LEDGER_PROFIT = JobFinancials.ledger_revenue - JobFinancials.ledger_cost
LEDGER_MARGIN = LEDGER_PROFIT / func.nullif(JobFinancials.ledger_revenue, 0)


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


async def compute_financials(db: AsyncSession, run: SyncRun) -> dict:
    """Total every job's money lines in one statement. The database does the adding up."""
    line = MoneyLine
    is_invoice = line.kind == "customer_invoice"
    is_bill = line.kind == "vendor_bill"
    late = and_(
        is_invoice, line.status == "SENT", line.amount > line.paid_amount, line.due_date < run.as_of
    )

    def total(column, where):
        return func.coalesce(func.sum(column).filter(where), 0)

    invoiced = total(line.amount, is_invoice)
    collected = total(line.paid_amount, is_invoice)
    totals = (
        select(
            Job.id,
            literal(run.id),
            Job.contract_value,
            Job.budget,
            total(line.amount, line.kind == "ops_cost"),
            total(line.amount, line.kind == "ledger_cost"),
            total(line.amount - line.paid_amount, is_bill),
            total(line.amount, line.kind == "ledger_revenue"),
            invoiced,
            total(line.amount, and_(is_invoice, line.status == "SENT")),
            collected,
            invoiced - collected,
            total(line.amount - line.paid_amount, late),
        )
        .outerjoin(line, line.job_id == Job.id)
        .group_by(Job.id)
    )
    await db.execute(
        insert(JobFinancials).from_select(
            [
                "job_id", "sync_run_id", "contract_value", "budget", "ops_cost", "ledger_cost",
                "unpaid_bills", "ledger_revenue", "invoiced", "sent", "collected", "owed", "past_due",
            ],
            totals,
        )
    )
    written = await db.scalar(
        select(func.count()).select_from(JobFinancials).where(JobFinancials.sync_run_id == run.id)
    )
    return {"jobs": written}


async def latest_run_id(db: AsyncSession) -> int | None:
    """The most recent sync that finished. Readers always use this one."""
    return await db.scalar(
        select(SyncRun.id).where(SyncRun.status == "succeeded").order_by(SyncRun.id.desc()).limit(1)
    )
