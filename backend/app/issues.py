"""Sync step 4: find where the three systems disagree.

Each issue type is one check, and each check is one SQL query that returns
only the rows that are findings. A finding becomes an issue with a stable key
(type plus the record it is about), so the same problem is the same issue on
every sync and keeps its owner, status and history.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Integer, and_, cast, delete, exists, func, literal, or_, select, text, type_coerce
from sqlalchemy.dialects.postgresql import aggregate_order_by, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.errors import InvalidRequestError, InvalidStateError
from app.models import (
    Company,
    Issue,
    IssueEvent,
    IssueEvidence,
    IssueType,
    Job,
    JobFinancials,
    JobOwner,
    MoneyLine,
    SourceRecord,
    SyncRun,
)

FINANCE_QUEUE = "Finance queue"
ZERO = Decimal(0)
UNSENT_STATUSES = ("APPROVED", "DRAFT", "SYNC_FAILED")
POSTED_STATUSES = ("POSTED", "POSTING_FAILED")

# key, title, severity, about, tolerance, unit, description
ISSUE_TYPES = [
    ("closed_bills", "Closed with unpaid vendor bills", "high", "cash", None, None,
     "The job is closed but a vendor bill on it is still unpaid."),
    ("past_due", "Customer invoice past due", "high", "cash", None, None,
     "A sent invoice still has a balance after its due date."),
    ("not_sent", "Invoice not sent", "high", "billing", None, None,
     "An invoice is approved, still a draft, or failed to reach accounting."),
    ("over_contract", "Cost above contract", "high", "cost", None, None,
     "The budget or the cost so far is higher than the contract value."),
    ("closed_month", "Bill in a closed month, not in ledger", "high", "cash", None, None,
     "A vendor bill is dated in a month finance has closed and has no ledger entry."),
    ("cost_disagree", "Ops and ledger cost disagree", "medium", "cost", Decimal("0.02"), "ratio",
     "The project team's cost total and the ledger's differ by more than the tolerance."),
    ("no_ledger_cost", "Cost missing from ledger", "medium", "cost", None, None,
     "The project team has logged cost and the ledger has none for the job."),
    ("rev_invoiced", "Ledger revenue differs from invoiced", "medium", "billing", Decimal("0.02"), "ratio",
     "Revenue in the ledger and the job's invoices differ by more than the tolerance."),
    ("underbilled", "Completed, not fully billed", "medium", "billing", Decimal("1"), "usd",
     "Work is complete and invoices total less than the contract by more than the tolerance."),
    ("bill_overdue", "Vendor bill failed or overdue", "medium", "cash", None, None,
     "A vendor bill failed to post, or is posted and past its due date."),
    ("discount", "Early-pay discount at risk", "medium", "cash", None, None,
     "A bill from a vendor with discount terms is not yet approved and the deadline has not passed."),
    ("no_job", "Vendor bill with no job", "medium", "cost", None, None,
     "A vendor bill is not assigned to any job."),
    ("no_owner", "No operations owner", "medium", "ownership", None, None,
     "The job has no ops manager assigned."),
]


async def ensure_issue_types(db: AsyncSession) -> None:
    """Add any issue type that is missing. Existing rows keep their settings."""
    rows = [
        {
            "key": key, "title": title, "severity": severity, "about": about, "tolerance": tolerance,
            "tolerance_unit": unit, "description": description, "enabled": True, "sort_order": order,
        }
        for order, (key, title, severity, about, tolerance, unit, description) in enumerate(ISSUE_TYPES)
    ]
    await db.execute(insert(IssueType).values(rows).on_conflict_do_nothing(index_elements=["key"]))
    await db.flush()


@dataclass
class Finding:
    type_key: str
    subject: str
    amount: Decimal
    summary: str
    detail: str
    next_step: str
    action_label: str
    owner: str = FINANCE_QUEUE
    job_id: int | None = None
    document: str | None = None
    due_on: date | None = None
    evidence: list[int] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.type_key}:{self.subject}"


def money(value: Decimal) -> str:
    return f"${value:,.0f}"


def short_date(value: date) -> str:
    return f"{value:%b} {value.day}"


# --- Shared pieces of SQL ------------------------------------------------------

line = MoneyLine
fin = JobFinancials
customer = aliased(Company)
vendor = aliased(Company)


def _owner_name(role: str):
    return select(JobOwner.name).where(JobOwner.job_id == Job.id, JobOwner.role == role).correlate(Job).scalar_subquery()


OPS_MANAGER = _owner_name("ops_manager")
ACCOUNT_EXECUTIVE = _owner_name("account_executive")
# Who an issue goes to: the ops manager, else the account executive, else finance.
OWNER = func.coalesce(OPS_MANAGER, ACCOUNT_EXECUTIVE, FINANCE_QUEUE).label("owner")
VENDOR_NAME = func.coalesce(vendor.name, line.description, "unknown vendor").label("vendor")
OPEN_AMOUNT = (line.amount - line.paid_amount).label("open_amount")


def _line_ids(*kinds: str):
    """The job's money lines of these kinds, as an array, to cite as evidence."""
    return (
        select(func.array_agg(line.id))
        .where(line.job_id == Job.id, line.kind.in_(kinds))
        .correlate(Job)
        .scalar_subquery()
        .label("evidence")
    )


def _jobs(run: SyncRun, *columns):
    """Jobs joined to this run's totals. Each check adds its own WHERE."""
    return select(Job.id.label("job_id"), Job.job_number, OWNER, *columns).join(
        fin, and_(fin.job_id == Job.id, fin.sync_run_id == run.id)
    )


def _invoices(*columns):
    return (
        select(
            line.id.label("line_id"), line.doc_number, line.amount, line.status, line.line_date, line.due_date,
            Job.id.label("job_id"), OWNER, func.coalesce(customer.name, "the customer").label("customer"), *columns,
        )
        .join(Job, Job.id == line.job_id)
        .outerjoin(customer, customer.id == Job.customer_id)
        .where(line.kind == "customer_invoice")
    )


def _bills(*columns):
    return (
        select(
            line.id.label("line_id"), line.doc_number, line.amount, line.status, line.line_date, line.due_date,
            Job.id.label("job_id"), OWNER, VENDOR_NAME, *columns,
        )
        .outerjoin(Job, Job.id == line.job_id)
        .outerjoin(vendor, vendor.id == line.company_id)
        .where(line.kind == "vendor_bill")
    )


# --- The checks ----------------------------------------------------------------
# Each one asks the database for the rows that are findings and nothing else.
# Python only turns those rows into words.


async def closed_bills(db: AsyncSession, run: SyncRun, issue_type: IssueType) -> list[Finding]:
    label = line.doc_number + " from " + func.coalesce(line.description, "unknown vendor")
    rows = await db.execute(
        select(
            Job.id.label("job_id"), Job.job_number, Job.closed_on, OWNER,
            func.sum(line.amount - line.paid_amount).label("amount"),
            func.count().label("bills"),
            func.array_agg(line.id).label("evidence"),
            func.string_agg(label, aggregate_order_by(literal(", "), line.id)).label("names"),
        )
        .join(line, line.job_id == Job.id)
        .where(Job.stage == "CLOSED", line.kind == "vendor_bill", line.amount > line.paid_amount)
        .group_by(Job.id)
    )
    return [
        Finding(
            "closed_bills", r.job_number, r.amount,
            summary=f"{r.bills} {'bill' if r.bills == 1 else 'bills'} unpaid, job closed {short_date(r.closed_on)}",
            detail=f"Closed {short_date(r.closed_on)}. Still unpaid: {r.names}.",
            next_step="Confirm the bill is valid, then decide whether the job reopens.",
            action_label="Send to finance", owner=r.owner, job_id=r.job_id, evidence=r.evidence,
        )
        for r in rows
    ]


async def past_due(db: AsyncSession, run: SyncRun, issue_type: IssueType) -> list[Finding]:
    days_late = type_coerce(literal(run.as_of, Date) - line.due_date, Integer).label("days_late")
    rows = await db.execute(
        _invoices(OPEN_AMOUNT, days_late).where(
            line.status == "SENT", line.amount > line.paid_amount, line.due_date < run.as_of
        )
    )
    return [
        Finding(
            "past_due", r.doc_number, r.open_amount,
            summary=f"{r.doc_number}, {r.days_late} days past due",
            detail=f"{r.doc_number} to {r.customer}: {money(r.open_amount)} open, {r.days_late} days past due.",
            next_step="Call the customer's payables contact and log the outcome.",
            action_label="Log follow-up", owner=r.owner, job_id=r.job_id, evidence=[r.line_id], document=r.doc_number,
            due_on=r.due_date,
        )
        for r in rows
    ]


async def not_sent(db: AsyncSession, run: SyncRun, issue_type: IssueType) -> list[Finding]:
    rows = await db.execute(_invoices().where(line.status.in_(UNSENT_STATUSES)))
    found = []
    for r in rows:
        state, step, label = {
            "APPROVED": (f"approved {short_date(r.line_date)}", "Send it to the customer.", "Send invoice"),
            "DRAFT": ("still a draft", "Finish the draft and send it.", "Finish and send"),
            "SYNC_FAILED": ("failed to sync", "Retry the sync so the invoice can go out.", "Retry sync"),
        }[r.status]
        found.append(
            Finding(
                "not_sent", r.doc_number, r.amount,
                summary=f"{r.doc_number}, {state}",
                detail=f"{r.doc_number} to {r.customer} for {money(r.amount)}: {state}.",
                next_step=step, action_label=label, owner=r.owner, job_id=r.job_id, evidence=[r.line_id], document=r.doc_number,
            )
        )
    return found


async def over_contract(db: AsyncSession, run: SyncRun, issue_type: IssueType) -> list[Finding]:
    cost_so_far = func.greatest(fin.ops_cost, fin.ledger_cost)
    rows = await db.execute(
        _jobs(
            run, Job.contract_value, Job.budget, Job.planned_margin_pct,
            cost_so_far.label("cost_so_far"),
            (func.greatest(cost_so_far, Job.budget) - Job.contract_value).label("amount"),
            _line_ids("ops_cost", "ledger_cost"),
        ).where(or_(cost_so_far > Job.contract_value, Job.budget > Job.contract_value))
    )
    return [
        Finding(
            "over_contract", r.job_number, r.amount,
            summary=f"Cost {money(r.cost_so_far)}, contract {money(r.contract_value)}",
            detail=(
                f"Contract {money(r.contract_value)}. Budget {money(r.budget)}, cost so far "
                f"{money(r.cost_so_far)}. Planned margin still shows {r.planned_margin_pct:.0f}%."
            ),
            next_step="Review scope and pricing with the estimator.",
            action_label="Flag for review", owner=r.owner, job_id=r.job_id, evidence=r.evidence or [],
        )
        for r in rows
    ]


async def cost_disagree(db: AsyncSession, run: SyncRun, issue_type: IssueType) -> list[Finding]:
    gap = func.abs(fin.ops_cost - fin.ledger_cost)
    rows = await db.execute(
        _jobs(run, fin.ops_cost, fin.ledger_cost, gap.label("amount"), _line_ids("ops_cost", "ledger_cost")).where(
            fin.ops_cost > 0, fin.ledger_cost > 0, gap / fin.ledger_cost > (issue_type.tolerance or ZERO)
        )
    )
    return [
        Finding(
            "cost_disagree", r.job_number, r.amount,
            summary=f"Ops log {money(r.ops_cost)}, ledger {money(r.ledger_cost)}",
            detail=f"Ops log says {money(r.ops_cost)}, ledger says {money(r.ledger_cost)}.",
            next_step="Find the entries that explain the difference.",
            action_label="Reconcile costs", owner=r.owner, job_id=r.job_id, evidence=r.evidence or [],
        )
        for r in rows
    ]


async def no_ledger_cost(db: AsyncSession, run: SyncRun, issue_type: IssueType) -> list[Finding]:
    rows = await db.execute(
        _jobs(run, fin.ops_cost, _line_ids("ops_cost")).where(fin.ops_cost > 0, fin.ledger_cost == 0)
    )
    return [
        Finding(
            "no_ledger_cost", r.job_number, r.ops_cost,
            summary=f"Ops log {money(r.ops_cost)}, ledger $0",
            detail=f"Ops has logged {money(r.ops_cost)} and the ledger has nothing for this job.",
            next_step="Ask finance to book the cost.",
            action_label="Send to finance", owner=r.owner, job_id=r.job_id, evidence=r.evidence or [],
        )
        for r in rows
    ]


async def rev_invoiced(db: AsyncSession, run: SyncRun, issue_type: IssueType) -> list[Finding]:
    gap = func.abs(fin.ledger_revenue - fin.invoiced)
    rows = await db.execute(
        _jobs(
            run, fin.ledger_revenue, fin.invoiced, gap.label("amount"), _line_ids("ledger_revenue", "customer_invoice")
        ).where(fin.ledger_revenue > 0, gap / fin.ledger_revenue > (issue_type.tolerance or ZERO))
    )
    return [
        Finding(
            "rev_invoiced", r.job_number, r.amount,
            summary=f"Ledger {money(r.ledger_revenue)}, invoiced {money(r.invoiced)}",
            detail=f"Ledger shows {money(r.ledger_revenue)} of revenue. Invoices total {money(r.invoiced)}.",
            next_step="Check whether an invoice is missing.",
            action_label="Review billing", owner=r.owner, job_id=r.job_id, evidence=r.evidence or [],
        )
        for r in rows
    ]


async def underbilled(db: AsyncSession, run: SyncRun, issue_type: IssueType) -> list[Finding]:
    unbilled = Job.contract_value - fin.invoiced
    rows = await db.execute(
        _jobs(
            run, Job.contract_value, Job.completed_on, fin.invoiced, unbilled.label("amount"),
            _line_ids("customer_invoice"),
        ).where(Job.stage == "COMPLETED", unbilled > (issue_type.tolerance or ZERO))
    )
    return [
        Finding(
            "underbilled", r.job_number, r.amount,
            summary=f"Contract {money(r.contract_value)}, invoiced {money(r.invoiced)}",
            detail=(
                f"Work finished {short_date(r.completed_on)}. Contract {money(r.contract_value)}, "
                f"invoiced {money(r.invoiced)}."
            ),
            next_step="Draft the final invoice.",
            action_label="Draft invoice", owner=r.owner, job_id=r.job_id, evidence=r.evidence or [],
        )
        for r in rows
    ]


async def no_owner(db: AsyncSession, run: SyncRun, issue_type: IssueType) -> list[Finding]:
    executive = func.coalesce(ACCOUNT_EXECUTIVE, "nobody").label("executive")
    rows = await db.execute(_jobs(run, executive).where(OPS_MANAGER.is_(None)))
    return [
        Finding(
            "no_owner", r.job_number, ZERO,
            summary=f"Account executive is {r.executive}",
            detail=f"No ops manager is assigned. The account executive is {r.executive}.",
            next_step="Assign an ops manager.",
            action_label="Assign owner", owner=r.owner, job_id=r.job_id,
        )
        for r in rows
    ]


async def no_job(db: AsyncSession, run: SyncRun, issue_type: IssueType) -> list[Finding]:
    rows = await db.execute(_bills().where(line.job_id.is_(None)))
    return [
        Finding(
            "no_job", r.doc_number, r.amount,
            summary=f"{r.doc_number} from {r.vendor}",
            detail=f"{r.doc_number} from {r.vendor}, {money(r.amount)}, has no job assigned.",
            next_step="Assign it to a job or to overhead.",
            action_label="Assign job", owner=r.owner, job_id=r.job_id, evidence=[r.line_id], document=r.doc_number,
        )
        for r in rows
    ]


async def closed_month(db: AsyncSession, run: SyncRun, issue_type: IssueType) -> list[Finding]:
    # Last day of the most recent month finance has closed.
    month_end = (
        select(
            func.max(
                cast(
                    func.make_date(
                        cast(SourceRecord.payload["year"].astext, Integer),
                        cast(SourceRecord.payload["month"].astext, Integer),
                        1,
                    )
                    + text("interval '1 month - 1 day'"),
                    Date,
                )
            )
        )
        .where(
            SourceRecord.table_name == "accounting_periods",
            SourceRecord.last_seen_run_id == run.id,
            SourceRecord.payload["status"].astext == "CLOSED",
        )
        .scalar_subquery()
    )
    ledger = aliased(MoneyLine)
    in_ledger = exists().where(ledger.kind.like("ledger_%"), ledger.doc_number == line.doc_number)
    rows = await db.execute(_bills().where(line.line_date <= month_end, ~in_ledger))
    return [
        Finding(
            "closed_month", r.doc_number, r.amount,
            summary=f"{r.doc_number}, dated {short_date(r.line_date)}",
            detail=(
                f"{r.doc_number} from {r.vendor} is dated {short_date(r.line_date)}. "
                "That month is closed and the ledger has no entry for it."
            ),
            next_step="Finance decides whether to reopen the month or book it now.",
            action_label="Send to finance", owner=r.owner, job_id=r.job_id, evidence=[r.line_id], document=r.doc_number,
        )
        for r in rows
    ]


async def bill_overdue(db: AsyncSession, run: SyncRun, issue_type: IssueType) -> list[Finding]:
    rows = await db.execute(_bills().where(line.status.in_(POSTED_STATUSES), line.due_date < run.as_of))
    found = []
    for r in rows:
        posted = r.status == "POSTED"
        found.append(
            Finding(
                "bill_overdue", r.doc_number, r.amount,
                summary=f"{r.doc_number}, {'due ' + short_date(r.due_date) if posted else 'failed to post'}",
                detail=(
                    f"{r.doc_number} from {r.vendor}: "
                    f"{'posted but unpaid' if posted else 'failed to post'}, due {short_date(r.due_date)}."
                ),
                next_step="Release it for payment." if posted else "Retry the posting.",
                action_label="Release payment" if posted else "Retry posting",
                owner=r.owner, job_id=r.job_id, evidence=[r.line_id], document=r.doc_number, due_on=r.due_date,
            )
        )
    return found


async def discount(db: AsyncSession, run: SyncRun, issue_type: IssueType) -> list[Finding]:
    deadline = line.line_date + func.coalesce(vendor.discount_days, 0)
    rows = await db.execute(
        _bills(
            vendor.discount_pct, deadline.label("deadline"),
            (line.amount * vendor.discount_pct / 100).label("saving"),
        ).where(vendor.discount_pct.is_not(None), line.status.not_in(POSTED_STATUSES), deadline >= run.as_of)
    )
    return [
        Finding(
            "discount", r.doc_number, r.amount,
            summary=f"{r.doc_number}, save {money(r.saving)} by {short_date(r.deadline)}",
            detail=(
                f"{r.doc_number} from {r.vendor}, {money(r.amount)}, is "
                f"{r.status.lower().replace('_', ' ')}. Paying by {short_date(r.deadline)} saves "
                f"{money(r.saving)} ({r.discount_pct:g}%)."
            ),
            next_step="Approve it before the deadline.",
            action_label="Approve bill", owner=r.owner, job_id=r.job_id, evidence=[r.line_id], document=r.doc_number,
            due_on=r.deadline,
        )
        for r in rows
    ]


CHECKS = {
    check.__name__: check
    for check in (
        closed_bills, past_due, not_sent, over_contract, closed_month, cost_disagree, no_ledger_cost,
        rev_invoiced, underbilled, bill_overdue, discount, no_job, no_owner,
    )
}


async def detect(db: AsyncSession, run: SyncRun) -> list[Finding]:
    """Run every enabled check. Each is one query that returns only its findings."""
    found: list[Finding] = []
    for issue_type in await db.scalars(select(IssueType).where(IssueType.enabled).order_by(IssueType.sort_order)):
        found.extend(await CHECKS[issue_type.key](db, run, issue_type))
    return found


async def record_findings(db: AsyncSession, run: SyncRun, findings: list[Finding]) -> dict:
    """Match findings to existing issues by key, then open, update or clear."""
    # Only the issues this run can touch: the ones just found, and the ones still
    # open that may now need clearing. Old resolved and cleared issues stay unread.
    found_keys = [f.key for f in findings]
    touched = select(Issue).where(or_(Issue.key.in_(found_keys), Issue.status.in_(("open", "assigned"))))
    existing = {i.key: i for i in await db.scalars(touched)}
    stats = {"found": len(findings), "opened": 0, "reopened": 0, "cleared": 0, "unchanged": 0}
    seen: set[str] = set()

    for f in findings:
        seen.add(f.key)
        issue = existing.get(f.key)
        if issue is None:
            issue = Issue(
                key=f.key, type_key=f.type_key, subject=f.subject, owner=f.owner,
                status="open", first_seen_run_id=run.id, last_seen_run_id=run.id,
                amount=f.amount, summary=f.summary, detail=f.detail, next_step=f.next_step,
                action_label=f.action_label, job_id=f.job_id, document=f.document, due_on=f.due_on,
            )
            db.add(issue)
            await db.flush()
            db.add(IssueEvent(issue_id=issue.id, kind="opened", note=f"Found in sync {run.id}"))
            stats["opened"] += 1
        else:
            if issue.status == "cleared":
                issue.status = "open"
                issue.owner = f.owner
                db.add(IssueEvent(issue_id=issue.id, kind="reopened", note=f"Found again in sync {run.id}"))
                stats["reopened"] += 1
            else:
                stats["unchanged"] += 1
            issue.amount, issue.summary, issue.detail = f.amount, f.summary, f.detail
            issue.next_step, issue.action_label = f.next_step, f.action_label
            issue.job_id = f.job_id
            issue.document, issue.due_on = f.document, f.due_on
            issue.last_seen_run_id = run.id
        await db.flush()
        await db.execute(delete(IssueEvidence).where(IssueEvidence.issue_id == issue.id))
        if f.evidence:
            await db.execute(
                insert(IssueEvidence).values([{"issue_id": issue.id, "money_line_id": i} for i in set(f.evidence)])
            )

    for key, issue in existing.items():
        # A person's resolution stands. Only untouched or in-progress issues clear on their own.
        if key not in seen and issue.status in ("open", "assigned"):
            issue.status = "cleared"
            db.add(IssueEvent(issue_id=issue.id, kind="cleared", note=f"No longer found in sync {run.id}"))
            stats["cleared"] += 1

    await db.flush()
    return stats


async def find_issues(db: AsyncSession, run: SyncRun) -> dict:
    await ensure_issue_types(db)
    return await record_findings(db, run, await detect(db, run))


async def apply_action(
    db: AsyncSession, issue: Issue, action: str, actor: str, note: str | None = None, assignee: str | None = None
) -> None:
    """The only way a person changes an issue. Every action leaves an event."""

    def log(kind: str, text: str | None) -> None:
        db.add(IssueEvent(issue_id=issue.id, kind=kind, actor=actor, note=text))

    if action == "assign":
        if not assignee:
            raise InvalidRequestError("An assignee is required to assign an issue.")
        if issue.status in ("resolved", "cleared"):
            raise InvalidStateError(f"A {issue.status} issue cannot be assigned. Reopen it first.")
        issue.owner, issue.status = assignee, "assigned"
        log("assigned", note or f"Assigned to {assignee}")
    elif action == "comment":
        if not note:
            raise InvalidRequestError("A comment needs a note.")
        log("commented", note)
    elif action == "resolve":
        if not note:
            raise InvalidRequestError("Resolving an issue needs a note saying what was done.")
        if issue.status in ("resolved", "cleared"):
            raise InvalidStateError(f"The issue is already {issue.status}.")
        issue.status, issue.resolution_note = "resolved", note
        log("resolved", note)
    elif action == "reopen":
        if issue.status not in ("resolved", "cleared"):
            raise InvalidStateError("Only a resolved or cleared issue can be reopened.")
        issue.status, issue.resolution_note = "open", None
        log("reopened", note)
    else:
        raise InvalidRequestError(f"Unknown action '{action}'.")
    await db.flush()
