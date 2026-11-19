"""Step 4 of a sync: find where the three systems disagree.

Each issue type is one check. A finding becomes an issue with a stable key
(type plus the record it is about), so the same problem is the same issue on
every sync and keeps its owner, status and history.
"""

import calendar
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Company,
    Issue,
    IssueEvent,
    IssueEvidence,
    IssueType,
    Job,
    JobFinancials,
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


def ensure_issue_types(session: Session) -> None:
    """Add any issue type that is missing. Existing rows keep their settings."""
    rows = [
        {
            "key": key, "title": title, "severity": severity, "about": about, "tolerance": tolerance,
            "tolerance_unit": unit, "description": description, "enabled": True, "sort_order": order,
        }
        for order, (key, title, severity, about, tolerance, unit, description) in enumerate(ISSUE_TYPES)
    ]
    session.execute(insert(IssueType).values(rows).on_conflict_do_nothing(index_elements=["key"]))
    session.flush()


@dataclass
class Finding:
    type_key: str
    subject: str
    amount: Decimal
    summary: str
    detail: str
    next_step: str
    action_label: str
    job: Job | None = None
    evidence: list[int] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.type_key}:{self.subject}"


def money(value: Decimal) -> str:
    return f"${value:,.0f}"


def short_date(value: date) -> str:
    return f"{value:%b} {value.day}"


def closed_through(session: Session, run: SyncRun) -> date | None:
    """Last day of the most recent month finance has closed."""
    periods = session.scalars(
        select(SourceRecord.payload).where(
            SourceRecord.table_name == "accounting_periods", SourceRecord.last_seen_run_id == run.id
        )
    )
    closed = [(p["year"], p["month"]) for p in periods if p["status"] == "CLOSED"]
    if not closed:
        return None
    year, month = max(closed)
    return date(year, month, calendar.monthrange(year, month)[1])


def default_owner(job: Job | None) -> str:
    if job is None:
        return FINANCE_QUEUE
    by_role = {o.role: o.name for o in job.owners}
    return by_role.get("ops_manager") or by_role.get("account_executive") or FINANCE_QUEUE


def detect(session: Session, run: SyncRun) -> list[Finding]:
    types = {t.key: t for t in session.scalars(select(IssueType))}
    jobs = session.scalars(select(Job).options(selectinload(Job.owners), selectinload(Job.customer))).all()
    fin_by_job = {
        f.job_id: f for f in session.scalars(select(JobFinancials).where(JobFinancials.sync_run_id == run.id))
    }
    companies = {c.id: c for c in session.scalars(select(Company))}
    all_lines = session.scalars(select(MoneyLine)).all()
    lines_by_job: dict[int, list[MoneyLine]] = defaultdict(list)
    for line in all_lines:
        if line.job_id:
            lines_by_job[line.job_id].append(line)
    job_by_id = {j.id: j for j in jobs}
    ledger_docs = {l.doc_number for l in all_lines if l.kind.startswith("ledger_")}
    month_end = closed_through(session, run)

    found: list[Finding] = []

    def add(type_key: str, **kwargs) -> None:
        if types[type_key].enabled:
            found.append(Finding(type_key=type_key, **kwargs))

    def tolerance(type_key: str) -> Decimal:
        return types[type_key].tolerance or ZERO

    for job in jobs:
        fin = fin_by_job[job.id]
        lines = lines_by_job.get(job.id, [])
        of_kind = lambda *kinds: [l for l in lines if l.kind in kinds]  # noqa: E731
        ids = lambda items: [l.id for l in items]  # noqa: E731
        customer = job.customer.name if job.customer else "the customer"
        invoices, bills = of_kind("customer_invoice"), of_kind("vendor_bill")

        unpaid = [b for b in bills if b.amount > b.paid_amount]
        if job.stage == "CLOSED" and unpaid:
            names = ", ".join(f"{b.doc_number} from {b.description}" for b in unpaid)
            add(
                "closed_bills", subject=job.job_number, job=job, amount=fin.unpaid_bills,
                summary=f"{len(unpaid)} {'bill' if len(unpaid) == 1 else 'bills'} unpaid, job closed {short_date(job.closed_on)}",
                detail=f"Closed {short_date(job.closed_on)}. Still unpaid: {names}.",
                next_step="Confirm the bill is valid, then decide whether the job reopens.",
                action_label="Send to finance", evidence=ids(unpaid),
            )

        for inv in invoices:
            open_amount = inv.amount - inv.paid_amount
            if inv.status == "SENT" and open_amount > 0 and inv.due_date and inv.due_date < run.as_of:
                late = (run.as_of - inv.due_date).days
                add(
                    "past_due", subject=inv.doc_number, job=job, amount=open_amount,
                    summary=f"{inv.doc_number}, {late} days past due",
                    detail=f"{inv.doc_number} to {customer}: {money(open_amount)} open, {late} days past due.",
                    next_step="Call the customer's payables contact and log the outcome.",
                    action_label="Log follow-up", evidence=[inv.id],
                )
            if inv.status in UNSENT_STATUSES:
                state, step, label = {
                    "APPROVED": (f"approved {short_date(inv.line_date)}", "Send it to the customer.", "Send invoice"),
                    "DRAFT": ("still a draft", "Finish the draft and send it.", "Finish and send"),
                    "SYNC_FAILED": ("failed to sync", "Retry the sync so the invoice can go out.", "Retry sync"),
                }[inv.status]
                add(
                    "not_sent", subject=inv.doc_number, job=job, amount=inv.amount,
                    summary=f"{inv.doc_number}, {state}",
                    detail=f"{inv.doc_number} to {customer} for {money(inv.amount)}: {state}.",
                    next_step=step, action_label=label, evidence=[inv.id],
                )

        cost_so_far = max(fin.ops_cost, fin.ledger_cost)
        if cost_so_far > job.contract_value or job.budget > job.contract_value:
            add(
                "over_contract", subject=job.job_number, job=job,
                amount=max(cost_so_far, job.budget) - job.contract_value,
                summary=f"Cost {money(cost_so_far)}, contract {money(job.contract_value)}",
                detail=(
                    f"Contract {money(job.contract_value)}. Budget {money(job.budget)}, cost so far "
                    f"{money(cost_so_far)}. Planned margin still shows {job.planned_margin_pct:.0f}%."
                ),
                next_step="Review scope and pricing with the estimator.",
                action_label="Flag for review", evidence=ids(of_kind("ops_cost", "ledger_cost")),
            )

        if fin.ops_cost > 0 and fin.ledger_cost > 0:
            gap = abs(fin.ops_cost - fin.ledger_cost)
            if gap / fin.ledger_cost > tolerance("cost_disagree"):
                add(
                    "cost_disagree", subject=job.job_number, job=job, amount=gap,
                    summary=f"Ops log {money(fin.ops_cost)}, ledger {money(fin.ledger_cost)}",
                    detail=f"Ops log says {money(fin.ops_cost)}, ledger says {money(fin.ledger_cost)}.",
                    next_step="Find the entries that explain the difference.",
                    action_label="Reconcile costs", evidence=ids(of_kind("ops_cost", "ledger_cost")),
                )

        if fin.ops_cost > 0 and fin.ledger_cost == 0:
            add(
                "no_ledger_cost", subject=job.job_number, job=job, amount=fin.ops_cost,
                summary=f"Ops log {money(fin.ops_cost)}, ledger $0",
                detail=f"Ops has logged {money(fin.ops_cost)} and the ledger has nothing for this job.",
                next_step="Ask finance to book the cost.",
                action_label="Send to finance", evidence=ids(of_kind("ops_cost")),
            )

        if fin.ledger_revenue > 0:
            gap = abs(fin.ledger_revenue - fin.invoiced)
            if gap / fin.ledger_revenue > tolerance("rev_invoiced"):
                add(
                    "rev_invoiced", subject=job.job_number, job=job, amount=gap,
                    summary=f"Ledger {money(fin.ledger_revenue)}, invoiced {money(fin.invoiced)}",
                    detail=f"Ledger shows {money(fin.ledger_revenue)} of revenue. Invoices total {money(fin.invoiced)}.",
                    next_step="Check whether an invoice is missing.",
                    action_label="Review billing", evidence=ids(of_kind("ledger_revenue", "customer_invoice")),
                )

        if job.stage == "COMPLETED" and job.contract_value - fin.invoiced > tolerance("underbilled"):
            add(
                "underbilled", subject=job.job_number, job=job, amount=job.contract_value - fin.invoiced,
                summary=f"Contract {money(job.contract_value)}, invoiced {money(fin.invoiced)}",
                detail=(
                    f"Work finished {short_date(job.completed_on)}. Contract {money(job.contract_value)}, "
                    f"invoiced {money(fin.invoiced)}."
                ),
                next_step="Draft the final invoice.", action_label="Draft invoice", evidence=ids(invoices),
            )

        roles = {o.role: o.name for o in job.owners}
        if "ops_manager" not in roles:
            executive = roles.get("account_executive", "nobody")
            add(
                "no_owner", subject=job.job_number, job=job, amount=ZERO,
                summary=f"Account executive is {executive}",
                detail=f"No ops manager is assigned. The account executive is {executive}.",
                next_step="Assign an ops manager.", action_label="Assign owner",
            )

    for bill in (l for l in all_lines if l.kind == "vendor_bill"):
        job = job_by_id.get(bill.job_id)
        vendor = companies.get(bill.company_id)
        vendor_name = vendor.name if vendor else (bill.description or "unknown vendor")
        common = {"subject": bill.doc_number, "job": job, "amount": bill.amount, "evidence": [bill.id]}

        if job is None:
            add(
                "no_job", **common,
                summary=f"{bill.doc_number} from {vendor_name}",
                detail=f"{bill.doc_number} from {vendor_name}, {money(bill.amount)}, has no job assigned.",
                next_step="Assign it to a job or to overhead.", action_label="Assign job",
            )

        if month_end and bill.line_date and bill.line_date <= month_end and bill.doc_number not in ledger_docs:
            add(
                "closed_month", **common,
                summary=f"{bill.doc_number}, dated {short_date(bill.line_date)}",
                detail=(
                    f"{bill.doc_number} from {vendor_name} is dated {short_date(bill.line_date)}. "
                    "That month is closed and the ledger has no entry for it."
                ),
                next_step="Finance decides whether to reopen the month or book it now.",
                action_label="Send to finance",
            )

        if bill.status in POSTED_STATUSES and bill.due_date and bill.due_date < run.as_of:
            posted = bill.status == "POSTED"
            add(
                "bill_overdue", **common,
                summary=f"{bill.doc_number}, {'due ' + short_date(bill.due_date) if posted else 'failed to post'}",
                detail=(
                    f"{bill.doc_number} from {vendor_name}: "
                    f"{'posted but unpaid' if posted else 'failed to post'}, due {short_date(bill.due_date)}."
                ),
                next_step="Release it for payment." if posted else "Retry the posting.",
                action_label="Release payment" if posted else "Retry posting",
            )

        if vendor and vendor.discount_pct and bill.status not in POSTED_STATUSES and bill.line_date:
            deadline = bill.line_date + timedelta(days=vendor.discount_days or 0)
            if deadline >= run.as_of:
                saving = bill.amount * vendor.discount_pct / 100
                add(
                    "discount", **common,
                    summary=f"{bill.doc_number}, save {money(saving)} by {short_date(deadline)}",
                    detail=(
                        f"{bill.doc_number} from {vendor_name}, {money(bill.amount)}, is "
                        f"{bill.status.lower().replace('_', ' ')}. Paying by {short_date(deadline)} saves "
                        f"{money(saving)} ({vendor.discount_pct:g}%)."
                    ),
                    next_step="Approve it before the deadline.", action_label="Approve bill",
                )

    return found


def record_findings(session: Session, run: SyncRun, findings: list[Finding]) -> dict:
    """Match findings to existing issues by key, then open, update or clear."""
    existing = {i.key: i for i in session.scalars(select(Issue))}
    stats = {"found": len(findings), "opened": 0, "reopened": 0, "cleared": 0, "unchanged": 0}
    seen: set[str] = set()

    for f in findings:
        seen.add(f.key)
        issue = existing.get(f.key)
        if issue is None:
            issue = Issue(
                key=f.key, type_key=f.type_key, subject=f.subject, owner=default_owner(f.job),
                status="open", first_seen_run_id=run.id, last_seen_run_id=run.id,
                amount=f.amount, summary=f.summary, detail=f.detail, next_step=f.next_step,
                action_label=f.action_label, job_id=f.job.id if f.job else None,
            )
            issue.events.append(IssueEvent(kind="opened", note=f"Found in sync {run.id}"))
            session.add(issue)
            stats["opened"] += 1
        else:
            if issue.status == "cleared":
                issue.status = "open"
                issue.owner = default_owner(f.job)
                issue.events.append(IssueEvent(kind="reopened", note=f"Found again in sync {run.id}"))
                stats["reopened"] += 1
            else:
                stats["unchanged"] += 1
            issue.amount, issue.summary, issue.detail = f.amount, f.summary, f.detail
            issue.next_step, issue.action_label = f.next_step, f.action_label
            issue.job_id = f.job.id if f.job else None
            issue.last_seen_run_id = run.id
        session.flush()
        session.execute(delete(IssueEvidence).where(IssueEvidence.issue_id == issue.id))
        if f.evidence:
            session.execute(
                insert(IssueEvidence).values([{"issue_id": issue.id, "money_line_id": i} for i in set(f.evidence)])
            )

    for key, issue in existing.items():
        # A person's resolution stands. Only untouched or in-progress issues clear on their own.
        if key not in seen and issue.status in ("open", "assigned"):
            issue.status = "cleared"
            issue.events.append(IssueEvent(kind="cleared", note=f"No longer found in sync {run.id}"))
            stats["cleared"] += 1

    session.flush()
    return stats


def find_issues(session: Session, run: SyncRun) -> dict:
    ensure_issue_types(session)
    return record_findings(session, run, detect(session, run))


class IssueActionError(ValueError):
    pass


def apply_action(
    session: Session, issue: Issue, action: str, actor: str, note: str | None = None, assignee: str | None = None
) -> Issue:
    """The only way a person changes an issue. Every action leaves an event."""
    if action == "assign":
        if not assignee:
            raise IssueActionError("An assignee is required to assign an issue")
        if issue.status in ("resolved", "cleared"):
            raise IssueActionError(f"A {issue.status} issue cannot be assigned. Reopen it first")
        issue.owner, issue.status = assignee, "assigned"
        issue.events.append(IssueEvent(kind="assigned", actor=actor, note=note or f"Assigned to {assignee}"))
    elif action == "comment":
        if not note:
            raise IssueActionError("A comment needs a note")
        issue.events.append(IssueEvent(kind="commented", actor=actor, note=note))
    elif action == "resolve":
        if not note:
            raise IssueActionError("Resolving an issue needs a note saying what was done")
        if issue.status in ("resolved", "cleared"):
            raise IssueActionError(f"The issue is already {issue.status}")
        issue.status, issue.resolution_note = "resolved", note
        issue.events.append(IssueEvent(kind="resolved", actor=actor, note=note))
    elif action == "reopen":
        if issue.status not in ("resolved", "cleared"):
            raise IssueActionError("Only a resolved or cleared issue can be reopened")
        issue.status, issue.resolution_note = "open", None
        issue.events.append(IssueEvent(kind="reopened", actor=actor, note=note))
    else:
        raise IssueActionError(f"Unknown action '{action}'")
    session.flush()
    return issue
