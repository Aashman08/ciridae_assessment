"""Turns our tables into the shapes the API returns."""

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Issue, Job, JobFinancials, MoneyLine, SyncRun

ACTIVE = ("open", "assigned")


def line_view(line: MoneyLine) -> dict:
    return {
        "id": line.id,
        "kind": line.kind,
        "doc_number": line.doc_number,
        "description": line.description,
        "job_number": line.job.job_number if line.job else None,
        "company": line.company.name if line.company else None,
        "amount": line.amount,
        "paid_amount": line.paid_amount,
        "open_amount": line.amount - line.paid_amount,
        "line_date": line.line_date,
        "due_date": line.due_date,
        "status": line.status,
        "cost_category": line.cost_category,
        "source_table": line.source_table,
        "source_record_id": line.source_record_id,
    }


def issue_view(issue: Issue) -> dict:
    return {
        "id": issue.id,
        "key": issue.key,
        "type_key": issue.type_key,
        "title": issue.type.title,
        "severity": issue.type.severity,
        "about": issue.type.about,
        "job_number": issue.job.job_number if issue.job else None,
        "job_name": issue.job.name if issue.job else None,
        "subject": issue.subject,
        "amount": issue.amount,
        "summary": issue.summary,
        "detail": issue.detail,
        "next_step": issue.next_step,
        "action_label": issue.action_label,
        "owner": issue.owner,
        "status": issue.status,
        "resolution_note": issue.resolution_note,
        "first_seen_run_id": issue.first_seen_run_id,
        "last_seen_run_id": issue.last_seen_run_id,
        "updated_at": issue.updated_at,
    }


def issue_detail_view(issue: Issue) -> dict:
    return {
        **issue_view(issue),
        "evidence": [line_view(e.line) for e in issue.evidence],
        "events": issue.events,
    }


def owner_name(job: Job, role: str) -> str | None:
    return next((o.name for o in job.owners if o.role == role), None)


def job_view(job: Job, fin: JobFinancials, issues: list[Issue]) -> dict:
    top = max(issues, key=lambda i: i.amount, default=None)
    return {
        "job_number": job.job_number,
        "name": job.name,
        "customer": job.customer.name if job.customer else None,
        "stage": job.stage,
        "branch": job.branch,
        "service_line": job.service_line,
        "ops_manager": owner_name(job, "ops_manager"),
        "account_executive": owner_name(job, "account_executive"),
        "contract_value": fin.contract_value,
        "budget": fin.budget,
        "planned_margin_pct": job.planned_margin_pct,
        "ledger_revenue": fin.ledger_revenue,
        "invoiced": fin.invoiced,
        "sent": fin.sent,
        "collected": fin.collected,
        "owed": fin.owed,
        "past_due": fin.past_due,
        "ops_cost": fin.ops_cost,
        "ledger_cost": fin.ledger_cost,
        "unpaid_bills": fin.unpaid_bills,
        "issue_count": len(issues),
        "top_issue": {"type_key": top.type_key, "title": top.type.title, "amount": top.amount} if top else None,
    }


def load_jobs(session: Session, run: SyncRun, owner: str | None = None) -> list[tuple[Job, JobFinancials, list[Issue]]]:
    """Every job with its totals for this run and its active issues."""
    jobs = session.scalars(select(Job).options(selectinload(Job.owners), selectinload(Job.customer))).all()
    fins = {f.job_id: f for f in session.scalars(select(JobFinancials).where(JobFinancials.sync_run_id == run.id))}
    issues_by_job: dict[int, list[Issue]] = defaultdict(list)
    for issue in session.scalars(select(Issue).where(Issue.status.in_(ACTIVE), Issue.job_id.is_not(None))):
        issues_by_job[issue.job_id].append(issue)
    rows = [(job, fins[job.id], issues_by_job.get(job.id, [])) for job in jobs if job.id in fins]
    if owner:
        rows = [r for r in rows if (owner_name(r[0], "ops_manager") or "").lower() == owner.lower()]
    return rows
