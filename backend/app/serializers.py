"""Conversions from database entities to API response models."""

from decimal import Decimal

from app.financials import (
    COST_LABELS,
    REVENUE_LABELS,
    CostBasis,
    RevenueBasis,
    cost_for,
    profit,
    revenue_for,
)
from app.models import Issue, IssueType, Job, JobFinancials, MoneyLine
from app.schemas import (
    EventResponse,
    FigureOption,
    IssueDetailResponse,
    IssueResponse,
    IssueTypeResponse,
    JobDetailResponse,
    JobSummaryResponse,
    LineResponse,
    ProfitResponse,
    TopIssue,
)

ZERO = Decimal(0)


def line_response(line: MoneyLine) -> LineResponse:
    return LineResponse(
        id=line.id,
        kind=line.kind,
        doc_number=line.doc_number,
        description=line.description,
        job_number=line.job.job_number if line.job else None,
        company=line.company.name if line.company else None,
        amount=line.amount,
        paid_amount=line.paid_amount,
        open_amount=line.amount - line.paid_amount,
        line_date=line.line_date,
        due_date=line.due_date,
        status=line.status,
        cost_category=line.cost_category,
        source_table=line.source_table,
        source_record_id=line.source_record_id,
    )


def _issue_fields(issue: Issue) -> dict:
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


def issue_response(issue: Issue) -> IssueResponse:
    return IssueResponse(**_issue_fields(issue))


def issue_detail_response(issue: Issue) -> IssueDetailResponse:
    return IssueDetailResponse(
        **_issue_fields(issue),
        evidence=[line_response(e.line) for e in issue.evidence],
        events=[EventResponse.model_validate(e) for e in issue.events],
    )


def issue_type_response(issue_type: IssueType, open_count: int, open_amount: Decimal) -> IssueTypeResponse:
    return IssueTypeResponse(
        key=issue_type.key,
        title=issue_type.title,
        severity=issue_type.severity,
        about=issue_type.about,
        description=issue_type.description,
        enabled=issue_type.enabled,
        tolerance=issue_type.tolerance,
        tolerance_unit=issue_type.tolerance_unit,
        open_count=open_count,
        open_amount=open_amount,
    )


def owner_name(job: Job, role: str) -> str | None:
    return next((o.name for o in job.owners if o.role == role), None)


def _job_fields(job: Job, fin: JobFinancials, issues: list[Issue]) -> dict:
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
        "top_issue": TopIssue(type_key=top.type_key, title=top.type.title, amount=top.amount) if top else None,
    }


def job_summary_response(job: Job, fin: JobFinancials, issues: list[Issue]) -> JobSummaryResponse:
    return JobSummaryResponse(**_job_fields(job, fin, issues))


def job_detail_response(
    job: Job,
    fin: JobFinancials,
    issues: list[Issue],
    lines: list[MoneyLine],
    revenue: RevenueBasis,
    cost: CostBasis,
) -> JobDetailResponse:
    """One job with every revenue and cost figure side by side, and profit for the chosen pair."""
    return JobDetailResponse(
        **_job_fields(job, fin, issues),
        estimated_value=job.estimated_value,
        original_contract_value=job.original_contract_value,
        won_on=job.won_on,
        on_site_on=job.on_site_on,
        planned_finish_on=job.planned_finish_on,
        completed_on=job.completed_on,
        closed_on=job.closed_on,
        cancelled_on=job.cancelled_on,
        crm_status=job.crm_status,
        revenue_options=[
            FigureOption(basis=b, label=label, description=text, amount=revenue_for(fin, b))
            for b, (label, text) in REVENUE_LABELS.items()
        ],
        cost_options=[
            FigureOption(basis=b, label=label, description=text, amount=cost_for(fin, b))
            for b, (label, text) in COST_LABELS.items()
        ],
        profit=ProfitResponse(**profit(fin, revenue, cost), planned_margin_pct=job.planned_margin_pct),
        issues=[issue_response(i) for i in sorted(issues, key=lambda i: i.amount, reverse=True)],
        invoices=[line_response(l) for l in lines if l.kind == "customer_invoice"],
        vendor_bills=[line_response(l) for l in lines if l.kind == "vendor_bill"],
    )
