"""Reconciliation operations: running a sync, reading jobs and issues, acting on issues.

Every endpoint goes through this client. It owns the database session and the
transaction for one request, and calls the pipeline steps and serializers.
"""

from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import and_, exists, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import database
from app.connector import Connector, ExportConnector
from app.errors import (
    InvalidRequestError,
    IssueNotFoundError,
    IssueTypeNotFoundError,
    JobNotFoundError,
    NoSyncYetError,
    SourceRecordNotFoundError,
    SyncRunNotFoundError,
)
from app.financials import CostBasis, RevenueBasis, compute_financials, latest_run_id
from app.issues import UNSENT_STATUSES, apply_action, find_issues
from app.landing import land
from app.models import (
    Issue,
    IssueEvidence,
    IssueType,
    Job,
    JobFinancials,
    JobOwner,
    MoneyLine,
    SourceRecord,
    SyncRun,
)
from app.normalize import normalize
from app.schemas import (
    CashSummary,
    ContractToCash,
    IssueAction,
    IssueDetailResponse,
    IssueFilters,
    IssueResponse,
    IssuesByType,
    IssueTypeResponse,
    IssueTypeUpdate,
    JobDetailResponse,
    JobFilters,
    JobSummaryResponse,
    LineFilters,
    LineResponse,
    ListResponse,
    Paging,
    SourceRecordResponse,
    SummaryResponse,
    SyncRunResponse,
)
from app.serializers import (
    issue_detail_response,
    issue_response,
    issue_type_response,
    job_detail_response,
    job_summary_response,
    line_response,
)

ACTIVE = ("open", "assigned")
ZERO = Decimal(0)
INVOICE, BILL = "customer_invoice", "vendor_bill"


def owned_by(owner: str):
    """SQL condition: the job's ops manager is this person."""
    return exists().where(
        JobOwner.job_id == Job.id,
        JobOwner.role == "ops_manager",
        func.lower(JobOwner.name) == owner.lower(),
    )


def total_of(column, where=None):
    """Sum of a column as SQL, optionally only over rows matching a condition. Zero when empty."""
    summed = func.sum(column)
    return func.coalesce(summed.filter(where) if where is not None else summed, 0)


class ReconClient:
    """One request's operations; the factory manages the database session lifetime."""

    def __init__(self, db: AsyncSession, request_id: str, connector: Connector | None = None) -> None:
        self.db = db
        self.request_id = request_id
        self.connector = connector or ExportConnector(database.source_engine, database.settings.source_schema)

    # --- Service -----------------------------------------------------------------

    async def ping(self) -> dict[str, str]:
        await self.db.execute(text("select 1"))
        return {"status": "ok"}

    # --- Sync runs ---------------------------------------------------------------

    async def run_sync(self, as_of: date | None = None) -> SyncRunResponse:
        """Read the source systems, rebuild the job records and re-check every issue."""
        if as_of is None:
            # The export's own date. Measured against today, every invoice in a
            # months-old export would look late.
            exported = await self.connector.metadata("dataset_as_of")
            as_of = date.fromisoformat(exported) if exported else datetime.now(UTC).date()

        run = SyncRun(as_of=as_of, status="running", stats={})
        self.db.add(run)
        await self.db.commit()
        run_id = run.id

        try:
            run.stats = {
                "land": await land(self.db, run, self.connector),
                "normalize": await normalize(self.db, run),
                "financials": await compute_financials(self.db, run),
                "issues": await find_issues(self.db, run),
            }
            run.status = "succeeded"
            run.finished_at = datetime.now(UTC)
            await self.db.commit()
        except Exception as exc:
            # Nothing from a failed run is kept except the record that it failed.
            await self.db.rollback()
            failed = await self.db.get(SyncRun, run_id, populate_existing=True)
            failed.status = "failed"
            failed.error = f"{type(exc).__name__}: {exc}"
            failed.finished_at = datetime.now(UTC)
            await self.db.commit()
            raise
        return SyncRunResponse.model_validate(run)

    async def list_sync_runs(self, paging: Paging) -> ListResponse[SyncRunResponse]:
        total = await self.db.scalar(select(func.count()).select_from(SyncRun))
        runs = await self.db.scalars(
            select(SyncRun).order_by(SyncRun.id.desc()).offset(paging.offset).limit(paging.limit)
        )
        return self._page([SyncRunResponse.model_validate(r) for r in runs], total, paging)

    async def get_sync_run(self, run_id: int) -> SyncRunResponse:
        run = await self.db.get(SyncRun, run_id)
        if run is None:
            raise SyncRunNotFoundError(run_id)
        return SyncRunResponse.model_validate(run)

    # --- Summary -----------------------------------------------------------------

    async def get_summary(self, owner: str | None = None) -> SummaryResponse:
        """Where cash is stuck and what needs attention. Each invoice and bill is counted once."""
        run = await self._current_run()
        job_scope = [owned_by(owner)] if owner else []
        live = Job.stage != "CANCELLED"
        fin = JobFinancials

        jobs = (
            await self.db.execute(
                select(
                    func.count().label("job_count"),
                    total_of(fin.owed).label("owed"),
                    total_of(fin.past_due).label("past_due"),
                    total_of(fin.contract_value, live).label("contract_value"),
                    total_of(fin.ledger_revenue, live).label("earned"),
                    total_of(fin.invoiced, live).label("invoiced"),
                    total_of(fin.sent, live).label("sent"),
                    total_of(fin.collected, live).label("collected"),
                )
                .select_from(fin)
                .join(Job, Job.id == fin.job_id)
                .where(fin.sync_run_id == run.id, *job_scope)
            )
        ).one()

        line = MoneyLine
        is_invoice, is_bill = line.kind == INVOICE, line.kind == BILL
        unsent = and_(is_invoice, line.status.in_(UNSENT_STATUSES))
        unpaid = and_(is_bill, line.amount > line.paid_amount)
        line_scope = [line.job_id.in_(select(Job.id).where(owned_by(owner)))] if owner else []
        lines = (
            await self.db.execute(
                select(
                    func.count().filter(is_invoice).label("invoice_count"),
                    total_of(line.amount, unsent).label("not_sent"),
                    func.count().filter(unsent).label("not_sent_count"),
                    total_of(line.amount - line.paid_amount, unpaid).label("bills_unpaid"),
                    func.count().filter(unpaid).label("bills_count"),
                ).where(line.kind.in_((INVOICE, BILL)), *line_scope)
            )
        ).one()

        issue_scope = [Issue.status.in_(ACTIVE)]
        if owner:
            issue_scope.append(func.lower(Issue.owner) == owner.lower())
        amount = total_of(Issue.amount)
        by_type = (
            await self.db.execute(
                select(Issue.type_key, IssueType.title, IssueType.severity, func.count().label("count"), amount.label("amount"))
                .join(IssueType, IssueType.key == Issue.type_key)
                .where(*issue_scope)
                .group_by(Issue.type_key, IssueType.title, IssueType.severity, IssueType.sort_order)
                .order_by(amount.desc(), IssueType.sort_order)
            )
        ).all()
        jobs_with_issues = await self.db.scalar(select(func.count(Issue.job_id.distinct())).where(*issue_scope))

        return SummaryResponse(
            sync_run_id=run.id,
            as_of=run.as_of,
            owner=owner,
            job_count=jobs.job_count,
            cash=CashSummary(
                owed=jobs.owed,
                past_due=jobs.past_due,
                invoices_not_sent=lines.not_sent,
                invoices_not_sent_count=lines.not_sent_count,
                vendor_bills_unpaid=lines.bills_unpaid,
                vendor_bills_count=lines.bills_count,
                invoice_count=lines.invoice_count,
            ),
            contract_to_cash=ContractToCash(
                contract_value=jobs.contract_value,
                earned=jobs.earned,
                invoiced=jobs.invoiced,
                sent=jobs.sent,
                collected=jobs.collected,
            ),
            open_issue_count=sum(row.count for row in by_type),
            jobs_with_issues=jobs_with_issues,
            issues_by_type=[
                IssuesByType(type_key=r.type_key, title=r.title, severity=r.severity, count=r.count, amount=r.amount)
                for r in by_type
            ],
        )

    # --- Jobs --------------------------------------------------------------------

    async def list_jobs(self, filters: JobFilters) -> ListResponse[JobSummaryResponse]:
        """Jobs with their totals from each system, most issues first."""
        run = await self._current_run()
        issue_count = (
            select(func.count())
            .where(Issue.job_id == Job.id, Issue.status.in_(ACTIVE))
            .correlate(Job)
            .scalar_subquery()
        )
        where = [JobFinancials.sync_run_id == run.id]
        if filters.stage:
            where.append(Job.stage == filters.stage.upper())
        if filters.branch:
            where.append(func.lower(Job.branch) == filters.branch.lower())
        if filters.owner:
            where.append(owned_by(filters.owner))
        if filters.has_issues is not None:
            where.append(issue_count > 0 if filters.has_issues else issue_count == 0)

        joined = select(Job, JobFinancials).join(JobFinancials, JobFinancials.job_id == Job.id).where(*where)
        total = await self.db.scalar(
            select(func.count()).select_from(Job).join(JobFinancials, JobFinancials.job_id == Job.id).where(*where)
        )
        rows = (
            await self.db.execute(
                joined.options(selectinload(Job.owners), selectinload(Job.customer))
                .order_by(issue_count.desc(), Job.contract_value.desc(), Job.job_number)
                .offset(filters.offset)
                .limit(filters.limit)
            )
        ).all()
        issues = await self._active_issues_by_job([job.id for job, _ in rows])
        return self._page(
            [job_summary_response(job, fin, issues.get(job.id, [])) for job, fin in rows], total, filters
        )

    async def get_job(
        self,
        job_number: str,
        revenue: RevenueBasis = RevenueBasis.ledger,
        cost: CostBasis = CostBasis.ledger,
    ) -> JobDetailResponse:
        job, fin = await self._job(job_number)
        issues = (await self._active_issues_by_job([job.id])).get(job.id, [])
        lines = await self._lines(MoneyLine.job_id == job.id, MoneyLine.kind.in_((INVOICE, BILL)))
        return job_detail_response(job, fin, issues, lines, revenue, cost)

    async def list_job_lines(self, job_number: str, kind: str | None = None) -> list[LineResponse]:
        """Every money line on the job. Each one names the source record it came from."""
        job, _ = await self._job(job_number)
        where = [MoneyLine.job_id == job.id]
        if kind:
            where.append(MoneyLine.kind == kind)
        return [line_response(l) for l in await self._lines(*where)]

    # --- Invoices and vendor bills -----------------------------------------------

    async def list_lines(self, filters: LineFilters) -> ListResponse[LineResponse]:
        """Money lines of one kind across jobs, largest open amount first."""
        where = [MoneyLine.kind == filters.kind]
        if filters.owner:
            await self._current_run()
            where.append(MoneyLine.job_id.in_(select(Job.id).where(owned_by(filters.owner))))
        if filters.no_job is not None:
            where.append(MoneyLine.job_id.is_(None) if filters.no_job else MoneyLine.job_id.is_not(None))

        total = await self.db.scalar(select(func.count()).select_from(MoneyLine).where(*where))
        lines = await self.db.scalars(
            select(MoneyLine)
            .where(*where)
            .options(selectinload(MoneyLine.job), selectinload(MoneyLine.company))
            .order_by((MoneyLine.amount - MoneyLine.paid_amount).desc(), MoneyLine.doc_number, MoneyLine.id)
            .offset(filters.offset)
            .limit(filters.limit)
        )
        return self._page([line_response(l) for l in lines], total, filters)

    # --- Issues ------------------------------------------------------------------

    async def list_issues(self, filters: IssueFilters) -> ListResponse[IssueResponse]:
        """The work queue: what is wrong, how much it is worth and who has it. Largest first."""
        where = []
        if filters.status == "active":
            where.append(Issue.status.in_(ACTIVE))
        elif filters.status != "all":
            where.append(Issue.status == filters.status)
        if filters.type:
            where.append(Issue.type_key == filters.type)
        if filters.owner:
            where.append(func.lower(Issue.owner) == filters.owner.lower())
        if filters.severity:
            where.append(Issue.type_key.in_(select(IssueType.key).where(IssueType.severity == filters.severity)))
        if filters.job:
            where.append(Issue.job_id.in_(select(Job.id).where(Job.job_number == filters.job.upper())))

        total = await self.db.scalar(select(func.count()).select_from(Issue).where(*where))
        issues = await self.db.scalars(
            select(Issue)
            .where(*where)
            .options(selectinload(Issue.type), selectinload(Issue.job))
            .order_by(Issue.amount.desc(), Issue.key)
            .offset(filters.offset)
            .limit(filters.limit)
        )
        return self._page([issue_response(i) for i in issues], total, filters)

    async def get_issue(self, issue_id: int) -> IssueDetailResponse:
        return issue_detail_response(await self._issue(issue_id))

    async def act_on_issue(self, issue_id: int, payload: IssueAction) -> IssueDetailResponse:
        """Assign, comment on, resolve or reopen. Recorded here only; nothing goes to the source systems."""
        # Lock the row so two people acting at once are applied one after the other.
        issue = await self.db.scalar(select(Issue).where(Issue.id == issue_id).with_for_update())
        if issue is None:
            raise IssueNotFoundError(issue_id)
        await apply_action(self.db, issue, payload.action, payload.actor, payload.note, payload.assignee)
        await self.db.commit()
        return issue_detail_response(await self._issue(issue_id))

    # --- Issue types -------------------------------------------------------------

    async def list_issue_types(self) -> list[IssueTypeResponse]:
        """The checks, with their settings and how much each has found."""
        found = await self._found_by_type()
        types = await self.db.scalars(select(IssueType).order_by(IssueType.sort_order))
        return [issue_type_response(t, *found.get(t.key, (0, ZERO))) for t in types]

    async def update_issue_type(self, key: str, payload: IssueTypeUpdate) -> IssueTypeResponse:
        """Switch a check on or off, or change its tolerance. Takes effect on the next sync."""
        issue_type = await self.db.get(IssueType, key)
        if issue_type is None:
            raise IssueTypeNotFoundError(key)
        if payload.enabled is not None:
            issue_type.enabled = payload.enabled
        if payload.tolerance is not None:
            if issue_type.tolerance_unit is None:
                raise InvalidRequestError(f"'{issue_type.title}' has no tolerance to set.")
            issue_type.tolerance = payload.tolerance
        await self.db.commit()
        found = await self._found_by_type(key)
        return issue_type_response(issue_type, *found.get(key, (0, ZERO)))

    # --- Source records ----------------------------------------------------------

    async def get_source_record(self, record_id: int) -> SourceRecordResponse:
        """The untouched source row behind any number."""
        record = await self.db.get(SourceRecord, record_id)
        if record is None:
            raise SourceRecordNotFoundError(record_id)
        return SourceRecordResponse.model_validate(record)

    # --- Shared reads ------------------------------------------------------------

    @staticmethod
    def _page(items: list, total: int, paging: Paging) -> ListResponse:
        """Wrap one page of rows. The database has already filtered, sorted and cut it."""
        return ListResponse(data=items, total=total, has_more=paging.offset + len(items) < total)

    async def _current_run(self) -> SyncRun:
        """The latest finished sync. Everything that is read comes from it."""
        run_id = await latest_run_id(self.db)
        if run_id is None:
            raise NoSyncYetError()
        return await self.db.get(SyncRun, run_id)

    async def _job(self, job_number: str) -> tuple[Job, JobFinancials]:
        run = await self._current_run()
        row = (
            await self.db.execute(
                select(Job, JobFinancials)
                .join(JobFinancials, JobFinancials.job_id == Job.id)
                .where(Job.job_number == job_number.upper(), JobFinancials.sync_run_id == run.id)
                .options(selectinload(Job.owners), selectinload(Job.customer))
            )
        ).one_or_none()
        if row is None:
            raise JobNotFoundError(job_number)
        return row.Job, row.JobFinancials

    async def _active_issues_by_job(self, job_ids: list[int]) -> dict[int, list[Issue]]:
        """Open and assigned issues for just the jobs being returned."""
        by_job: dict[int, list[Issue]] = defaultdict(list)
        if not job_ids:
            return by_job
        issues = await self.db.scalars(
            select(Issue)
            .where(Issue.job_id.in_(job_ids), Issue.status.in_(ACTIVE))
            .options(selectinload(Issue.type), selectinload(Issue.job))
        )
        for issue in issues:
            by_job[issue.job_id].append(issue)
        return by_job

    async def _found_by_type(self, key: str | None = None) -> dict[str, tuple[int, Decimal]]:
        """How many active issues each type has, and what they add up to."""
        query = select(Issue.type_key, func.count(), total_of(Issue.amount)).where(Issue.status.in_(ACTIVE))
        if key:
            query = query.where(Issue.type_key == key)
        rows = await self.db.execute(query.group_by(Issue.type_key))
        return {type_key: (count, amount) for type_key, count, amount in rows}

    async def _lines(self, *where) -> list[MoneyLine]:
        query = (
            select(MoneyLine)
            .where(*where)
            .options(selectinload(MoneyLine.job), selectinload(MoneyLine.company))
            .order_by(MoneyLine.line_date, MoneyLine.id)
        )
        return list(await self.db.scalars(query))

    async def _issue(self, issue_id: int) -> Issue:
        evidence_line = selectinload(Issue.evidence).selectinload(IssueEvidence.line)
        query = (
            select(Issue)
            .where(Issue.id == issue_id)
            .options(
                selectinload(Issue.type),
                selectinload(Issue.job),
                selectinload(Issue.events),
                evidence_line.selectinload(MoneyLine.job),
                evidence_line.selectinload(MoneyLine.company),
            )
            .execution_options(populate_existing=True)
        )
        issue = await self.db.scalar(query)
        if issue is None:
            raise IssueNotFoundError(issue_id)
        return issue


@asynccontextmanager
async def create_recon_client(request_id: str, connector: Connector | None = None) -> AsyncIterator[ReconClient]:
    """Create a client for one operation and always release its database session."""
    async with database.SessionLocal() as db:
        try:
            yield ReconClient(db, request_id, connector)
        except Exception:
            await db.rollback()
            raise
