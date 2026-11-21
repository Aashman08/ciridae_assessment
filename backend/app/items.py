"""Items: the things a person fixes.

The thirteen checks each fire on their own, so one unpaid vendor bill can be
three issues. A person does not fix checks. They fix the bill. This module
groups the issues about one invoice, one bill or one gap on a job into a single
item, turns the checks into tags on it, and says by fixed rules what work
fixes that kind of item.

Detection is untouched: issues are still found, stored and cleared one check at
a time. Grouping happens when they are read.
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from app.models import Issue, Job
from app.schemas import (
    EventResponse,
    ItemAction,
    ItemResponse,
    ItemTag,
    JobItems,
    JobSuggestion,
    Suggestion,
)
from app.serializers import _owner_role, line_response, owner_name

ACTIVE = ("open", "assigned")

# Which kind of item each check belongs to.
KIND_OF = {
    "past_due": "invoice_unpaid",
    "not_sent": "invoice_not_sent",
    "bill_overdue": "bill_stuck",
    "closed_month": "bill_stuck",
    "discount": "bill_stuck",
    "closed_bills": "bill_stuck",
    "no_job": "bill_no_job",
    "cost_disagree": "cost_gap",
    "no_ledger_cost": "cost_gap",
    "over_contract": "cost_gap",
    "rev_invoiced": "billing_gap",
    "underbilled": "billing_gap",
    "no_owner": "no_ops_manager",
    "slow_start": "late_start",
    "past_finish": "stalled",
    "no_activity": "stalled",
    "budget_burn": "budget_risk",
}
# The same, short enough to sit several to a line on a job's row.
SHORT = {
    "invoice_unpaid": "Invoice unpaid",
    "invoice_not_sent": "Invoice not sent",
    "bill_stuck": "Bill unpaid",
    "bill_no_job": "Bill with no job",
    "cost_gap": "Cost gap",
    "billing_gap": "Billing gap",
    "late_start": "Slow to start",
    "stalled": "Stalled",
    "budget_risk": "Spending ahead",
    "no_ops_manager": "No ops manager",
    "flagged": "Flagged",
}
TITLES = {
    "invoice_unpaid": "Customer invoice unpaid",
    "invoice_not_sent": "Customer invoice not sent",
    "bill_stuck": "Vendor bill unpaid",
    "bill_no_job": "Vendor bill with no job",
    "cost_gap": "Cost does not agree",
    "billing_gap": "Billing does not agree",
    "late_start": "Slow to start",
    "stalled": "Stalled",
    "budget_risk": "Spending ahead of schedule",
    "no_ops_manager": "No ops manager",
    # A finding of a check a person added. Its own title is the check's name.
    "flagged": "Flagged by a check",
}
# Items about when work happens. They are the ops manager's to answer.
SCHEDULE_KINDS = ("late_start", "stalled", "budget_risk")
# Items about one document, and the order kinds are listed in on a job.
DOCUMENT_KINDS = ("invoice_unpaid", "invoice_not_sent", "bill_stuck", "bill_no_job")
ORDER = list(TITLES)

# A bill at one of these stages is waiting on the project team, not on finance.
WITH_OPS = ("DRAFT", "NEEDS_REVIEW", "PENDING_PROJECT_APPROVAL")
AWAITING_APPROVAL = (*WITH_OPS, "PENDING_FINANCE_APPROVAL", "PENDING_CORPORATE_REVIEW")
STATUS_WORDS = {
    "DRAFT": "Still a draft",
    "APPROVED": "Approved, not sent",
    "SYNC_FAILED": "Failed to reach accounting",
    "NEEDS_REVIEW": "Needs review",
    "PENDING_PROJECT_APPROVAL": "Waiting on project approval",
    "PENDING_FINANCE_APPROVAL": "Waiting on finance approval",
    "PENDING_CORPORATE_REVIEW": "Waiting on corporate review",
    "POSTING_FAILED": "Posting failed",
}


def kind_of(type_key: str) -> str:
    """The kind of item an issue type's findings are. Checks people added are all "flagged"."""
    return KIND_OF.get(type_key, "flagged")


def working_days_from(start: date, days: int) -> date:
    """The date `days` working days after `start`, skipping weekends."""
    day = start
    while days > 0:
        day += timedelta(days=1)
        if day.weekday() < 5:
            days -= 1
    return day


def work_for(kind: str, status: str | None) -> ItemAction:
    """The work that fixes an item of this kind. Fixed rules: the same item always gets the same answer."""
    if kind == "invoice_unpaid":
        return ItemAction(key="message_customer", label="Chase the customer")
    if kind == "invoice_not_sent":
        return ItemAction(key="message_colleague", label="Get the invoice sent")
    if kind == "bill_stuck":
        label = "Get the bill approved" if status in AWAITING_APPROVAL else "Raise it with finance"
        return ItemAction(key="message_colleague", label=label)
    if kind == "bill_no_job":
        return ItemAction(key="code_bill", label="Suggest a job")
    if kind == "cost_gap":
        return ItemAction(key="message_colleague", label="Ask to reconcile costs")
    if kind == "billing_gap":
        return ItemAction(key="message_colleague", label="Ask to reconcile billing")
    if kind == "late_start":
        return ItemAction(key="message_colleague", label="Confirm the start")
    if kind == "stalled":
        return ItemAction(key="message_colleague", label="Ask for a status update")
    if kind == "budget_risk":
        return ItemAction(key="message_colleague", label="Ask for a cost forecast")
    if kind == "flagged":
        return ItemAction(key="message_colleague", label="Ask about it")
    return ItemAction(key="assign_ops_manager", label="Assign an ops manager")


def with_whom(kind: str, status: str | None) -> str:
    """Who a message about this item goes to inside the company: "ops" or "finance"."""
    if kind in SCHEDULE_KINDS or kind == "flagged":
        return "ops"
    if kind in ("invoice_not_sent", "bill_stuck") and status in WITH_OPS:
        return "ops"
    return "finance"


def what_to_ask(kind: str, status: str | None, document: str | None) -> str:
    """The one thing a message about this item asks for."""
    if kind == "invoice_unpaid":
        return f"Say when invoice {document} will be paid."
    if kind == "invoice_not_sent":
        return f"Approve invoice {document} so it can go out." if status == "DRAFT" else f"Send invoice {document} to the customer."
    if kind == "bill_stuck":
        if status in WITH_OPS:
            return f"Review and approve bill {document}."
        if status in AWAITING_APPROVAL:
            return f"Approve bill {document}."
        if status == "POSTING_FAILED":
            return f"Post bill {document} again; it failed to post."
        return f"Pay bill {document}, or say when it will be paid."
    if kind == "cost_gap":
        return "Reconcile the project team's cost total with the ledger for this job and say which is right."
    if kind == "billing_gap":
        return "Reconcile what has been invoiced with the revenue in the ledger for this job and say which is right."
    if kind == "late_start":
        return "Confirm the date the crew will be on site, and whether it can be brought forward."
    if kind == "stalled":
        return "Say where the job stands, what is holding it up, and the new finish date."
    if kind == "budget_risk":
        return "Give a forecast of the cost to finish, and say whether the budget will hold."
    if kind == "flagged":
        return "Say what is behind this and what will be done about it."
    return "Say who the ops manager for this job is."


def _item_key(issue: Issue) -> str:
    kind = kind_of(issue.type_key)
    on_document = kind in DOCUMENT_KINDS or kind == "flagged"
    subject = issue.document if on_document and issue.document else issue.job.job_number
    return f"{kind}:{subject}"


def _bills_cited(issue: Issue) -> list[str]:
    return sorted({e.line.doc_number for e in issue.evidence if e.line.kind == "vendor_bill" and e.line.doc_number})


def build_items(issues: list[Issue], as_of: date | None) -> list[ItemResponse]:
    """Group issues into items. Each issue needs its type, job, evidence lines and events loaded.

    `as_of` is the date of the last sync, and it is the clock for everything here: how
    late something is, and whether a follow-up date has arrived. The figures are true as
    of that date, so that is the day it is as far as they are concerned."""
    today = as_of or date.today()
    grouped: dict[str, list[Issue]] = defaultdict(list)
    for issue in issues:
        if issue.type_key == "closed_bills":
            # A closed job with unpaid bills is a fact about each of those bills.
            for number in _bills_cited(issue):
                grouped[f"bill_stuck:{number}"].append(issue)
        else:
            grouped[_item_key(issue)].append(issue)
    return [_item(key, members, as_of, today) for key, members in grouped.items()]


def _item(key: str, members: list[Issue], as_of: date | None, today: date) -> ItemResponse:
    kind, subject = key.split(":", 1)
    members = sorted(members, key=lambda i: (i.type.severity != "high", -i.amount, i.id))
    active = [i for i in members if i.status in ACTIVE]
    live = active or members
    lead = live[0]
    checks = [i.type_key for i in live]
    document = subject if kind in DOCUMENT_KINDS or (kind == "flagged" and lead.document) else None

    # The document itself, when the item is about one.
    lines = {e.line.id: e.line for i in members for e in i.evidence}
    own = next((l for l in lines.values() if document and l.doc_number == document and l.kind in ("vendor_bill", "customer_invoice")), None)
    status = own.status if own else None
    shown = [l for l in lines.values() if l is own] if own else list(lines.values())

    due = next((i.due_on for i in live if i.type_key in ("past_due", "bill_overdue") and i.due_on), None) or (own.due_date if own else None)
    if kind in SCHEDULE_KINDS:
        # The date the job was due to start or finish.
        due = next((i.due_on for i in live if i.due_on), None)
    late = (as_of - due).days if as_of and due and kind in ("invoice_unpaid", "bill_stuck") else 0

    tags: list[ItemTag] = []
    if status in STATUS_WORDS and kind in ("invoice_not_sent", "bill_stuck"):
        tags.append(ItemTag(key=status.lower(), label=STATUS_WORDS[status]))
    if late > 0:
        tags.append(ItemTag(key="late", label=f"{late} {'day' if late == 1 else 'days'} late"))
    if "discount" in checks:
        deadline = next(i.due_on for i in live if i.type_key == "discount")
        tags.append(ItemTag(key="discount", label=f"Discount ends {deadline.day} {deadline:%b}" if deadline else "Discount at risk"))
    if "closed_month" in checks:
        tags.append(ItemTag(key="closed_month", label="Closed month"))
    if "closed_bills" in checks:
        tags.append(ItemTag(key="job_closed", label="Job closed"))
    if "no_ledger_cost" in checks:
        tags.append(ItemTag(key="no_ledger_cost", label="Nothing in the ledger"))
    if "over_contract" in checks:
        tags.append(ItemTag(key="over_contract", label="Above contract"))
    if "underbilled" in checks:
        tags.append(ItemTag(key="underbilled", label="Complete, not fully billed"))
    if kind in SCHEDULE_KINDS:
        tags.extend(_schedule_tags(lead.job, live, as_of))
    if kind == "flagged" and len(live) > 1:
        # Several checks people added found the same record: one tag each.
        tags.extend(ItemTag(key="flagged", label=i.type.title) for i in live)

    follow_up = min((i.follow_up_on for i in active if i.follow_up_on), default=None)
    state = "done" if not active else "waiting" if follow_up and follow_up > today else "needs_action"
    action = work_for(kind, status)
    # One history for the item. Each check behind it was found, cleared or reopened by
    # the same sync, so those lines are kept once.
    events, told = [], set()
    for event in sorted({e.id: e for i in members for e in i.events}.values(), key=lambda e: (e.created_at, e.id)):
        same = (event.kind, event.actor, event.note)
        if event.actor == "system" and same in told:
            continue
        told.add(same)
        events.append(event)
    amount = (own.amount - own.paid_amount) if own else max((i.amount for i in live), default=Decimal(0))

    return ItemResponse(
        key=key,
        kind=kind,
        title=lead.type.title if kind == "flagged" else TITLES[kind],
        document=document,
        company=(own.company.name if own and own.company else own.description if own else None),
        job_number=lead.job.job_number if lead.job else None,
        job_name=lead.job.name if lead.job else None,
        amount=amount,
        severity="high" if any(i.type.severity == "high" for i in live) else "medium",
        tags=tags,
        due_on=due,
        days_late=late if late > 0 else None,
        owner=lead.owner,
        owner_role=_owner_role(lead),
        state=state,
        follow_up_on=follow_up,
        note_count=sum(1 for e in events if e.kind == "commented"),
        # A closed job's unpaid bills are described by the bill's own checks when it has any.
        details=[i.detail for i in live if i.type_key != "closed_bills" or len(live) == 1],
        resolution_note=None if active else lead.resolution_note,
        checks=checks,
        issue_ids=[i.id for i in members],
        action=action,
        suggestion=Suggestion(action=action, reason=None, follow_up_on=None, by="rule"),
        evidence=[line_response(l) for l in sorted(shown, key=lambda l: (l.line_date or date.min, l.id))],
        events=[EventResponse.model_validate(e) for e in events],
    )


def _schedule_tags(job: Job | None, issues: list[Issue], as_of: date | None) -> list[ItemTag]:
    """The figures that make a schedule item worth a look, as tags."""
    if job is None:
        return []
    today = as_of or date.today()
    checks = {issue.type_key: issue for issue in issues}
    tags: list[ItemTag] = []
    if job.urgent_reason:
        tags.append(ItemTag(key="urgent", label="Urgent"))
    if "slow_start" in checks and job.won_on:
        start = job.on_site_on or today
        tags.append(ItemTag(key="wait", label=f"{(start - job.won_on).days} days from win to start"))
        if job.on_site_on:
            tags.append(ItemTag(key="starts", label=f"Starts {job.on_site_on.day} {job.on_site_on:%b}"))
    if "past_finish" in checks and job.planned_finish_on:
        tags.append(ItemTag(key="late", label=f"{(today - job.planned_finish_on).days} days past finish"))
    if "no_activity" in checks:
        dates = [e.line.line_date for e in checks["no_activity"].evidence if e.line.line_date]
        if dates:
            tags.append(ItemTag(key="idle", label=f"No work logged for {(today - max(dates)).days} days"))
    if "budget_burn" in checks:
        lines = [e.line for e in checks["budget_burn"].evidence]
        cost = max(
            sum((l.amount for l in lines if l.kind == "ops_cost"), Decimal(0)),
            sum((l.amount for l in lines if l.kind == "ledger_cost"), Decimal(0)),
        )
        if job.budget:
            tags.append(ItemTag(key="spent", label=f"{cost / job.budget:.0%} of budget used"))
        if job.on_site_on and job.planned_finish_on and job.planned_finish_on > job.on_site_on:
            share = min(1, (today - job.on_site_on).days / (job.planned_finish_on - job.on_site_on).days)
            tags.append(ItemTag(key="time", label=f"{share:.0%} of time gone"))
    return tags


def fingerprint(items: list[ItemResponse]) -> str:
    """A job's items as a short string that changes whenever anything a review rests on changes."""
    parts = [
        f"{i.key}|{i.amount}|{i.state}|{i.follow_up_on}|{i.owner}|{i.note_count}|{len(i.source_notes)}|"
        f"{','.join(t.key + t.label for t in i.tags)}"
        for i in sorted(items, key=lambda i: i.key)
    ]
    return "\n".join(parts)


def group_by_job(items: list[ItemResponse], jobs: dict[str, Job]) -> list[JobItems]:
    """One group per job, most money flagged first. Bills with no job form a group of their own, listed first."""
    by_job: dict[str | None, list[ItemResponse]] = defaultdict(list)
    for item in items:
        by_job[item.job_number].append(item)

    groups = []
    for number, members in by_job.items():
        members.sort(key=lambda i: (i.state != "needs_action", ORDER.index(i.kind), -i.amount, i.key))
        tags: dict[str, ItemTag] = {}
        for item in members:
            tags.setdefault(item.kind, ItemTag(key=item.kind, label=SHORT[item.kind]))
        job = jobs.get(number) if number else None
        groups.append(
            JobItems(
                job_number=number,
                job_name=job.name if job else None,
                ops_manager=owner_name(job, "ops_manager") if job else None,
                flagged_amount=sum((i.amount for i in members if i.kind in DOCUMENT_KINDS), Decimal(0)),
                tags=list(tags.values()),
                items=members,
                suggestion=first_by_rule(members),
                reviewed_at=None,
            )
        )
    groups.sort(key=lambda g: (g.job_number is not None, -g.flagged_amount, -len(g.items), g.job_number or ""))
    return groups


def first_by_rule(items: list[ItemResponse]) -> JobSuggestion | None:
    """Without a review, the item to start with is the most serious one that needs action, then the largest."""
    waiting = [i for i in items if i.state == "needs_action"]
    if not waiting:
        return None
    first = min(waiting, key=lambda i: (i.severity != "high", -i.amount, i.key))
    return JobSuggestion(item_key=first.key, action=first.suggestion.action, reason=None, by="rule")
