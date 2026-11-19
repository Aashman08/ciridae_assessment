from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api import schemas as s
from app.api.deps import Paging, current_run, require_api_key
from app.api.views import ACTIVE, issue_detail_view, issue_view, job_view, line_view, load_jobs
from app.db import get_session
from app.models import Issue, IssueType, Job, MoneyLine, SourceRecord, SyncRun
from app.sync.financials import (
    COST_LABELS,
    REVENUE_LABELS,
    CostBasis,
    RevenueBasis,
    cost_for,
    profit,
    revenue_for,
)
from app.sync.issues import IssueActionError, apply_action
from app.sync.runner import run_sync

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])
ZERO = Decimal(0)


def not_found(what: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found")


# --- Sync runs ---------------------------------------------------------------


@router.post("/sync-runs", response_model=s.SyncRunOut, status_code=status.HTTP_201_CREATED, tags=["sync"])
def start_sync(body: s.SyncRunIn | None = None, session: Session = Depends(get_session)):
    """Pull from the source systems, rebuild the job records and re-check every issue."""
    return run_sync(session, as_of=body.as_of if body else None)


@router.get("/sync-runs", response_model=s.Page[s.SyncRunOut], tags=["sync"])
def list_sync_runs(paging: Paging = Depends(), session: Session = Depends(get_session)):
    return paging.page(session.scalars(select(SyncRun).order_by(SyncRun.id.desc())).all())


@router.get("/sync-runs/{run_id}", response_model=s.SyncRunOut, tags=["sync"])
def get_sync_run(run_id: int, session: Session = Depends(get_session)):
    run = session.get(SyncRun, run_id)
    if run is None:
        raise not_found("Sync run")
    return run


# --- Summary -----------------------------------------------------------------


@router.get("/summary", response_model=s.SummaryOut, tags=["summary"])
def summary(
    owner: str | None = Query(None, description="Limit to one ops manager's jobs and issues"),
    run: SyncRun = Depends(current_run),
    session: Session = Depends(get_session),
):
    """Where cash is stuck and what needs attention. Each invoice and bill is counted once."""
    rows = load_jobs(session, run, owner)
    job_ids = {job.id for job, _, _ in rows}
    live = [fin for job, fin, _ in rows if job.stage != "CANCELLED"]
    total = lambda attr, items: sum((getattr(f, attr) for f in items), ZERO)  # noqa: E731

    lines = session.scalars(select(MoneyLine).where(MoneyLine.kind.in_(("customer_invoice", "vendor_bill")))).all()
    if owner:
        lines = [l for l in lines if l.job_id in job_ids]
    unsent = [l for l in lines if l.kind == "customer_invoice" and l.status in ("APPROVED", "DRAFT", "SYNC_FAILED")]
    bills = [l for l in lines if l.kind == "vendor_bill" and l.amount > l.paid_amount]

    issues = session.scalars(select(Issue).where(Issue.status.in_(ACTIVE)).options(selectinload(Issue.type))).all()
    if owner:
        issues = [i for i in issues if i.owner.lower() == owner.lower()]
    by_type: dict[str, dict] = {}
    for issue in issues:
        entry = by_type.setdefault(
            issue.type_key,
            {"type_key": issue.type_key, "title": issue.type.title, "severity": issue.type.severity, "count": 0, "amount": ZERO},
        )
        entry["count"] += 1
        entry["amount"] += issue.amount

    all_fins = [fin for _, fin, _ in rows]
    return {
        "sync_run_id": run.id,
        "as_of": run.as_of,
        "owner": owner,
        "job_count": len(rows),
        "cash": {
            "owed": total("owed", all_fins),
            "past_due": total("past_due", all_fins),
            "invoices_not_sent": sum((l.amount for l in unsent), ZERO),
            "invoices_not_sent_count": len(unsent),
            "vendor_bills_unpaid": sum((l.amount - l.paid_amount for l in bills), ZERO),
            "vendor_bills_count": len(bills),
        },
        "contract_to_cash": {
            "contract_value": total("contract_value", live),
            "earned": total("ledger_revenue", live),
            "invoiced": total("invoiced", live),
            "sent": total("sent", live),
            "collected": total("collected", live),
        },
        "open_issue_count": len(issues),
        "jobs_with_issues": len({i.job_id for i in issues if i.job_id}),
        "issues_by_type": sorted(by_type.values(), key=lambda e: e["amount"], reverse=True),
    }


# --- Jobs --------------------------------------------------------------------


@router.get("/jobs", response_model=s.Page[s.JobSummary], tags=["jobs"])
def list_jobs(
    stage: str | None = Query(None, description="WORK_NOT_STARTED, IN_PROGRESS, COMPLETED, CLOSED or CANCELLED"),
    owner: str | None = Query(None, description="Ops manager's name"),
    branch: str | None = None,
    has_issues: bool | None = None,
    paging: Paging = Depends(),
    run: SyncRun = Depends(current_run),
    session: Session = Depends(get_session),
):
    """Jobs with their totals from each system, most issues first."""
    rows = load_jobs(session, run, owner)
    if stage:
        rows = [r for r in rows if r[0].stage == stage.upper()]
    if branch:
        rows = [r for r in rows if (r[0].branch or "").lower() == branch.lower()]
    if has_issues is not None:
        rows = [r for r in rows if bool(r[2]) == has_issues]
    rows.sort(key=lambda r: (-len(r[2]), -r[1].contract_value, r[0].job_number))
    return paging.page([job_view(*r) for r in rows])


def _job_row(session: Session, run: SyncRun, job_number: str):
    row = next((r for r in load_jobs(session, run) if r[0].job_number == job_number.upper()), None)
    if row is None:
        raise not_found(f"Job {job_number}")
    return row


def _lines(session: Session, *where) -> list[MoneyLine]:
    query = (
        select(MoneyLine)
        .where(*where)
        .options(selectinload(MoneyLine.job), selectinload(MoneyLine.company))
        .order_by(MoneyLine.line_date, MoneyLine.id)
    )
    return session.scalars(query).all()


@router.get("/jobs/{job_number}", response_model=s.JobDetail, tags=["jobs"])
def get_job(
    job_number: str,
    revenue: RevenueBasis = Query(RevenueBasis.ledger, description="Which revenue figure to use for profit"),
    cost: CostBasis = Query(CostBasis.ledger, description="Which cost figure to use for profit"),
    run: SyncRun = Depends(current_run),
    session: Session = Depends(get_session),
):
    """One job: every revenue and cost figure side by side, and profit for the pair chosen."""
    job, fin, issues = _job_row(session, run, job_number)
    lines = _lines(session, MoneyLine.job_id == job.id, MoneyLine.kind.in_(("customer_invoice", "vendor_bill")))
    return {
        **job_view(job, fin, issues),
        "estimated_value": job.estimated_value,
        "original_contract_value": job.original_contract_value,
        "won_on": job.won_on,
        "on_site_on": job.on_site_on,
        "planned_finish_on": job.planned_finish_on,
        "completed_on": job.completed_on,
        "closed_on": job.closed_on,
        "cancelled_on": job.cancelled_on,
        "crm_status": job.crm_status,
        "revenue_options": [
            {"basis": b, "label": label, "description": text, "amount": revenue_for(fin, b)}
            for b, (label, text) in REVENUE_LABELS.items()
        ],
        "cost_options": [
            {"basis": b, "label": label, "description": text, "amount": cost_for(fin, b)}
            for b, (label, text) in COST_LABELS.items()
        ],
        "profit": {**profit(fin, revenue, cost), "planned_margin_pct": job.planned_margin_pct},
        "issues": [issue_view(i) for i in sorted(issues, key=lambda i: i.amount, reverse=True)],
        "invoices": [line_view(l) for l in lines if l.kind == "customer_invoice"],
        "vendor_bills": [line_view(l) for l in lines if l.kind == "vendor_bill"],
    }


@router.get("/jobs/{job_number}/lines", response_model=list[s.LineOut], tags=["jobs"])
def get_job_lines(
    job_number: str,
    kind: str | None = Query(None, description="ops_cost, ledger_cost, ledger_revenue, vendor_bill, customer_invoice or customer_payment"),
    run: SyncRun = Depends(current_run),
    session: Session = Depends(get_session),
):
    """Every money line on the job. Each one names the source record it came from."""
    job, _, _ = _job_row(session, run, job_number)
    where = [MoneyLine.job_id == job.id]
    if kind:
        where.append(MoneyLine.kind == kind)
    return [line_view(l) for l in _lines(session, *where)]


# --- Invoices and vendor bills -----------------------------------------------


@router.get("/lines", response_model=s.Page[s.LineOut], tags=["lines"])
def list_lines(
    kind: str = Query(..., description="customer_invoice or vendor_bill, or any other money line kind"),
    owner: str | None = Query(None, description="Limit to one ops manager's jobs"),
    no_job: bool | None = Query(None, description="Only lines with no job assigned"),
    paging: Paging = Depends(),
    run: SyncRun = Depends(current_run),
    session: Session = Depends(get_session),
):
    """Money lines of one kind across jobs, largest open amount first."""
    lines = _lines(session, MoneyLine.kind == kind)
    if owner:
        job_ids = {job.id for job, _, _ in load_jobs(session, run, owner)}
        lines = [l for l in lines if l.job_id in job_ids]
    if no_job is not None:
        lines = [l for l in lines if (l.job_id is None) == no_job]
    lines.sort(key=lambda l: (-(l.amount - l.paid_amount), l.doc_number or ""))
    return paging.page([line_view(l) for l in lines])


# --- Issues ------------------------------------------------------------------


def _issue_query():
    return select(Issue).options(
        selectinload(Issue.type), selectinload(Issue.job), selectinload(Issue.events),
        selectinload(Issue.evidence),
    )


@router.get("/issues", response_model=s.Page[s.IssueOut], tags=["issues"])
def list_issues(
    type: str | None = Query(None, description="Issue type key, such as past_due"),
    owner: str | None = None,
    status: str = Query("active", description="active (open or assigned), open, assigned, resolved, cleared or all"),
    severity: str | None = Query(None, description="high or medium"),
    job: str | None = Query(None, description="Job number"),
    paging: Paging = Depends(),
    session: Session = Depends(get_session),
):
    """The work queue: what is wrong, how much it is worth and who has it. Largest first."""
    issues = session.scalars(_issue_query()).all()
    wanted = {"active": ACTIVE, "all": None}.get(status, (status,))
    if wanted:
        issues = [i for i in issues if i.status in wanted]
    if type:
        issues = [i for i in issues if i.type_key == type]
    if owner:
        issues = [i for i in issues if i.owner.lower() == owner.lower()]
    if severity:
        issues = [i for i in issues if i.type.severity == severity]
    if job:
        issues = [i for i in issues if i.job and i.job.job_number == job.upper()]
    issues.sort(key=lambda i: (-i.amount, i.key))
    return paging.page([issue_view(i) for i in issues])


def _issue(session: Session, issue_id: int) -> Issue:
    issue = session.scalar(_issue_query().where(Issue.id == issue_id))
    if issue is None:
        raise not_found("Issue")
    return issue


@router.get("/issues/{issue_id}", response_model=s.IssueDetail, tags=["issues"])
def get_issue(issue_id: int, session: Session = Depends(get_session)):
    """One issue with the money lines that prove it and everything that has happened to it."""
    return issue_detail_view(_issue(session, issue_id))


@router.post("/issues/{issue_id}/actions", response_model=s.IssueDetail, tags=["issues"])
def act_on_issue(issue_id: int, body: s.IssueActionIn, session: Session = Depends(get_session)):
    """Assign, comment on, resolve or reopen an issue. Recorded here only; nothing is sent to the source systems."""
    issue = _issue(session, issue_id)
    try:
        apply_action(session, issue, body.action, body.actor, body.note, body.assignee)
    except IssueActionError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    session.commit()
    session.expire_all()
    return issue_detail_view(_issue(session, issue_id))


# --- Issue types -------------------------------------------------------------


def _type_view(issue_type: IssueType, issues: list[Issue]) -> dict:
    mine = [i for i in issues if i.type_key == issue_type.key]
    return {
        "key": issue_type.key,
        "title": issue_type.title,
        "severity": issue_type.severity,
        "about": issue_type.about,
        "description": issue_type.description,
        "enabled": issue_type.enabled,
        "tolerance": issue_type.tolerance,
        "tolerance_unit": issue_type.tolerance_unit,
        "open_count": len(mine),
        "open_amount": sum((i.amount for i in mine), ZERO),
    }


@router.get("/issue-types", response_model=list[s.IssueTypeOut], tags=["issue types"])
def list_issue_types(session: Session = Depends(get_session)):
    """The checks, with their settings and how much each has found."""
    issues = session.scalars(select(Issue).where(Issue.status.in_(ACTIVE))).all()
    types = session.scalars(select(IssueType).order_by(IssueType.sort_order)).all()
    return [_type_view(t, issues) for t in types]


@router.patch("/issue-types/{key}", response_model=s.IssueTypeOut, tags=["issue types"])
def update_issue_type(key: str, body: s.IssueTypePatch, session: Session = Depends(get_session)):
    """Switch a check on or off, or change its tolerance. Takes effect on the next sync."""
    issue_type = session.get(IssueType, key)
    if issue_type is None:
        raise not_found("Issue type")
    if body.enabled is not None:
        issue_type.enabled = body.enabled
    if body.tolerance is not None:
        if issue_type.tolerance_unit is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This issue type has no tolerance to set")
        issue_type.tolerance = Decimal(str(body.tolerance))
    session.commit()
    issues = session.scalars(select(Issue).where(Issue.status.in_(ACTIVE))).all()
    return _type_view(issue_type, issues)


# --- Source records ----------------------------------------------------------


@router.get("/source-records/{record_id}", response_model=s.SourceRecordOut, tags=["source records"])
def get_source_record(record_id: int, session: Session = Depends(get_session)):
    """The untouched source row behind any number."""
    record = session.get(SourceRecord, record_id)
    if record is None:
        raise not_found("Source record")
    return record
