"""Reconciliation operations: running a sync, reading jobs and issues, acting on issues.

Every endpoint goes through this client. It owns the database session and the
transaction for one request, and calls the pipeline steps and serializers.
"""

from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TypeVar

from sqlalchemy import Date, and_, case, cast, delete, exists, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

import json
import logging

from agents.exceptions import AgentsException
from openai import APIStatusError, AuthenticationError, OpenAIError, RateLimitError

from app import assistant, coding, database, drafts, review
from app.coding import CodingCase
from app.connector import Connector, ExportConnector
from app.errors import (
    AskFailedError,
    AskNotConfiguredError,
    AskProviderError,
    InvalidRequestError,
    InvalidStateError,
    ItemNotFoundError,
    IssueNotFoundError,
    IssueTypeNotFoundError,
    JobNotFoundError,
    NoSyncYetError,
    SourceRecordNotFoundError,
    SyncRunNotFoundError,
)
from app.financials import (
    LEDGER_MARGIN,
    LEDGER_PROFIT,
    UNBILLED,
    CostBasis,
    RevenueBasis,
    compute_financials,
    contract_stages,
    latest_run_id,
    margin_pct,
    share_pct,
)
from app.issues import DOCUMENT_TYPES, FINANCE_QUEUE, UNSENT_STATUSES, apply_action, find_issues
from app.items import DOCUMENT_KINDS, KIND_OF, SCHEDULE_KINDS, TITLES, build_items, fingerprint, group_by_job, what_to_ask, with_whom, working_days_from
from app.landing import land
from app.models import (
    AskExchange,
    Company,
    Issue,
    IssueEvent,
    IssueEvidence,
    JobReview,
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
    AskMessage,
    AskRequest,
    AskResponse,
    CashSummary,
    CodingResponse,
    CostByCode,
    JobPace,
    OperationsResponse,
    OwnerLoad,
    UrgentStart,
    WaitingStart,
    Copied,
    CountedOnce,
    DocumentLine,
    DocumentParty,
    DocumentPayment,
    DocumentResponse,
    FinanceMonth,
    FinanceWeek,
    FinanceResponse,
    ReceivableAge,
    WorkKindProfit,
    ItemActionRequest,
    ItemFilters,
    ItemResponse,
    ItemsResponse,
    JobItems,
    SourceNote,
    CustomerBalance,
    DraftRequest,
    DraftResponse,
    PersonResponse,
    Recipient,
    SourceSystem,
    MonthTotal,
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
    ask_response,
    issue_detail_response,
    issue_response,
    issue_type_response,
    job_detail_response,
    job_summary_response,
    line_response,
    owner_name,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

# What grouping issues into items needs on top of that: each issue's records and its history.
def _item_parts():
    line = selectinload(Issue.evidence).selectinload(IssueEvidence.line)
    return (
        selectinload(Issue.type),
        selectinload(Issue.job).selectinload(Job.owners),
        selectinload(Issue.events),
        line.selectinload(MoneyLine.company),
        line.selectinload(MoneyLine.job).selectinload(Job.owners),
    )


ITEM_PARTS = _item_parts()

# What every issue read loads: its type, and its job with the people on it, which
# says why the issue's owner has it.
ISSUE_PARTS = (selectinload(Issue.type), selectinload(Issue.job).selectinload(Job.owners))

# How many earlier exchanges the model is shown, so a follow-up question makes sense.
ASK_MEMORY = 6

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


def to_day(value) -> date | None:
    """The date part of a source timestamp."""
    return date.fromisoformat(str(value)[:10]) if value else None


def _person(email: str | None) -> str:
    """A name from a work address: jenna.okafor@… is Jenna Okafor."""
    return " ".join(part.capitalize() for part in (email or "unknown").split("@")[0].split("."))


def _provider_message(error: APIStatusError) -> str:
    """The provider's own explanation, without its error-code wrapper."""
    body = error.body if isinstance(error.body, dict) else {}
    return str(body.get("message") or "Try again shortly.")


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
                    total_of(UNBILLED, live).label("unbilled"),
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

        # One invoice or bill can sit under several issue types. Counting the documents
        # themselves, once each, gives the money actually in question.
        flagged_lines = (
            select(IssueEvidence.money_line_id)
            .join(Issue, Issue.id == IssueEvidence.issue_id)
            .where(*issue_scope, Issue.type_key.in_(DOCUMENT_TYPES))
        )
        flagged = (
            await self.db.execute(
                select(func.count(), total_of(MoneyLine.amount - MoneyLine.paid_amount)).where(
                    MoneyLine.id.in_(flagged_lines), MoneyLine.kind.in_((INVOICE, BILL))
                )
            )
        ).one()

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
                stages=contract_stages(jobs.contract_value, jobs.invoiced, jobs.sent, jobs.collected, jobs.unbilled),
            ),
            open_issue_count=sum(row.count for row in by_type),
            open_item_count=(await self.list_items(ItemFilters(owner=owner))).item_count,
            jobs_with_issues=jobs_with_issues,
            issues_by_type=[
                IssuesByType(type_key=r.type_key, title=r.title, severity=r.severity, count=r.count, amount=r.amount)
                for r in by_type
            ],
            flagged_documents=CountedOnce(count=flagged[0], amount=flagged[1]),
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
        if filters.q:
            match = f"%{filters.q.strip()}%"
            customer = select(Company.id).where(Company.name.ilike(match))
            where.append(or_(Job.job_number.ilike(match), Job.name.ilike(match), Job.customer_id.in_(customer)))

        sort_by = {
            "issues": issue_count,
            "job_number": Job.job_number,
            "name": Job.name,
            "contract": Job.contract_value,
            "revenue": JobFinancials.ledger_revenue,
            "cost": JobFinancials.ledger_cost,
            "profit": LEDGER_PROFIT,
            "margin": LEDGER_MARGIN,
            "planned_margin": Job.planned_margin_pct,
            "owed": JobFinancials.owed,
        }[filters.sort]
        # A job with no margin yet goes last whichever way the list is sorted.
        first = (sort_by.asc() if filters.order == "asc" else sort_by.desc()).nulls_last()

        joined = select(Job, JobFinancials).join(JobFinancials, JobFinancials.job_id == Job.id).where(*where)
        total = await self.db.scalar(
            select(func.count()).select_from(Job).join(JobFinancials, JobFinancials.job_id == Job.id).where(*where)
        )
        rows = (
            await self.db.execute(
                joined.options(selectinload(Job.owners), selectinload(Job.customer))
                .order_by(first, Job.contract_value.desc(), Job.job_number)
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
        as_of = (await self._current_run()).as_of
        detail = job_detail_response(job, fin, issues, lines, revenue, cost, as_of)
        detail.items = await self._job_items(job, as_of)
        return detail

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
        if filters.status:
            where.append(MoneyLine.status == filters.status.upper())
        if filters.balance:
            where.append(MoneyLine.amount > MoneyLine.paid_amount)
        if filters.balance == "past_due":
            run = await self._current_run()
            where.extend([MoneyLine.status == "SENT", MoneyLine.due_date < run.as_of])

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

        high_first = case((IssueType.severity == "high", 1), else_=0)
        sort_by = {
            "amount": Issue.amount,
            "severity": select(high_first).where(IssueType.key == Issue.type_key).correlate(Issue).scalar_subquery(),
            "due": Issue.due_on,
            "follow_up": Issue.follow_up_on,
            "owner": Issue.owner,
        }[filters.sort]
        # Issues with no date go last whichever way the list is sorted.
        first = (sort_by.asc() if filters.order == "asc" else sort_by.desc()).nulls_last()

        total = await self.db.scalar(select(func.count()).select_from(Issue).where(*where))
        issues = await self.db.scalars(
            select(Issue)
            .where(*where)
            .options(*ISSUE_PARTS)
            .order_by(first, Issue.amount.desc(), Issue.key)
            .offset(filters.offset)
            .limit(filters.limit)
        )
        as_of = await self._as_of()
        return self._page([issue_response(i, as_of) for i in issues], total, filters)

    async def get_issue(self, issue_id: int) -> IssueDetailResponse:
        return await self._issue_detail(issue_id)

    async def list_people(self) -> list[PersonResponse]:
        """Everyone an issue can be given to: the ops managers and account executives
        named on jobs, and the finance queue."""
        rows = await self.db.execute(
            select(JobOwner.name, func.array_agg(JobOwner.role.distinct()))
            .group_by(JobOwner.name)
            .order_by(JobOwner.name)
        )
        people = [PersonResponse(name=name, roles=sorted(roles)) for name, roles in rows]
        return [*people, PersonResponse(name=FINANCE_QUEUE, roles=["finance"])]

    async def act_on_issue(self, issue_id: int, payload: IssueAction) -> IssueDetailResponse:
        """Assign, comment on, resolve or reopen. Recorded here only; nothing goes to the source systems."""
        # Lock the row so two people acting at once are applied one after the other.
        issue = await self.db.scalar(select(Issue).where(Issue.id == issue_id).with_for_update())
        if issue is None:
            raise IssueNotFoundError(issue_id)
        await apply_action(
            self.db, issue, payload.action, payload.actor, payload.note, payload.assignee,
            payload.follow_up_on, payload.clear_follow_up,
        )
        await self.db.commit()
        return await self._issue_detail(issue_id)

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
            if issue_type.tolerance_unit == "days" and (payload.tolerance < 1 or payload.tolerance != int(payload.tolerance)):
                raise InvalidRequestError("A tolerance in days must be a whole number of at least 1.")
            issue_type.tolerance = payload.tolerance
        await self.db.commit()
        found = await self._found_by_type(key)
        return issue_type_response(issue_type, *found.get(key, (0, ZERO)))

    # --- Customers ---------------------------------------------------------------

    async def list_customer_balances(self, owner: str | None = None, limit: int = 10) -> list[CustomerBalance]:
        """What each customer owes and how much of it is past due, largest first."""
        run = await self._current_run()
        open_amount = MoneyLine.amount - MoneyLine.paid_amount
        late = and_(MoneyLine.status == "SENT", open_amount > 0, MoneyLine.due_date < run.as_of)
        owed = total_of(open_amount)
        where = [MoneyLine.kind == INVOICE]
        if owner:
            where.append(MoneyLine.job_id.in_(select(Job.id).where(owned_by(owner))))
        rows = await self.db.execute(
            select(
                Company.name.label("customer"),
                func.count().filter(open_amount > 0).label("open_invoice_count"),
                owed.label("owed"),
                total_of(open_amount, late).label("past_due"),
            )
            .join(Company, Company.id == MoneyLine.company_id)
            .where(*where)
            .group_by(Company.id)
            .having(owed > 0)
            .order_by(owed.desc(), Company.name)
            .limit(limit)
        )
        return [CustomerBalance(**row._mapping) for row in rows]

    async def list_month_totals(self, kind: str, owner: str | None = None) -> list[MonthTotal]:
        """Customer invoices or vendor bills totalled by the calendar month they are dated, oldest first."""
        await self._current_run()
        month = func.to_char(MoneyLine.line_date, "YYYY-MM")
        where = [MoneyLine.kind == kind, MoneyLine.line_date.is_not(None)]
        if owner:
            where.append(MoneyLine.job_id.in_(select(Job.id).where(owned_by(owner))))
        rows = await self.db.execute(
            select(
                month.label("month"),
                func.count().label("count"),
                total_of(MoneyLine.amount).label("amount"),
                total_of(MoneyLine.paid_amount).label("paid"),
                total_of(MoneyLine.amount - MoneyLine.paid_amount).label("unpaid"),
                total_of(MoneyLine.amount, and_(MoneyLine.kind == INVOICE, MoneyLine.status == "SENT")).label("sent"),
            )
            .where(*where)
            .group_by(month)
            .order_by(month)
        )
        return [MonthTotal(**row._mapping) for row in rows]

    # --- Ask ---------------------------------------------------------------------

    async def ask(self, payload: AskRequest) -> AskResponse:
        """Answer a question in plain words, using only the fixed tools in `assistant`,
        and save the exchange so the conversation is still there later."""
        run = await self._current_run()
        history = await self._recent_conversation(payload.asked_by)
        answer = await self._with_model(assistant.answer(self, payload, run.as_of, history))

        # Only a finished answer is kept. A failed question leaves no trace in the conversation.
        exchange = AskExchange(
            asked_by=payload.asked_by,
            owner=payload.owner,
            question=payload.question,
            **answer.model_dump(mode="json", exclude={"as_of"}),
            as_of=answer.as_of,
        )
        self.db.add(exchange)
        await self.db.commit()
        return ask_response(exchange)

    async def _with_model(self, work: Awaitable[T]) -> T:
        """Run something that calls the model, turning the provider's failures into
        errors that say what is actually wrong."""
        if not assistant.is_configured():
            close = getattr(work, "close", None)
            if close:
                close()
            raise AskNotConfiguredError()
        try:
            return await work
        except AuthenticationError as exc:
            logger.warning("Ask: OpenAI rejected the API key request_id=%s", self.request_id)
            raise AskProviderError("OpenAI rejected the API key. Check OPENAI_API_KEY in backend/.env.") from exc
        except RateLimitError as exc:
            # Covers both "slow down" and "this account has no credits". OpenAI's own
            # sentence says which, and is safe to show.
            logger.warning("Ask: OpenAI refused the request request_id=%s: %s", self.request_id, exc)
            raise AskProviderError(f"OpenAI refused the request. {_provider_message(exc)}") from exc
        except (AgentsException, OpenAIError) as exc:
            # The model ran out of turns, or the provider failed part-way.
            logger.warning("Ask failed request_id=%s: %s: %s", self.request_id, type(exc).__name__, exc)
            raise AskFailedError() from exc

    # --- Follow-up drafts --------------------------------------------------------

    async def draft_follow_up(self, issue_id: int, payload: DraftRequest) -> DraftResponse:
        """Draft a follow-up starting from one issue. It is drafted for the item the issue belongs to."""
        issue = await self._issue(issue_id)
        if issue.status not in ACTIVE:
            raise InvalidStateError(f"A {issue.status} issue needs no follow-up. Reopen it first.")
        kind = KIND_OF[issue.type_key]
        if issue.type_key == "closed_bills":
            subject = next((e.line.doc_number for e in issue.evidence if e.line.kind == BILL), None)
        else:
            subject = issue.document if kind in DOCUMENT_KINDS else (issue.job.job_number if issue.job else None)
        return await self.draft_for_item(f"{kind}:{subject}", payload)

    # --- Items ---------------------------------------------------------------------

    async def list_items(self, filters: ItemFilters) -> ItemsResponse:
        """What needs fixing, grouped by job. One item per invoice, bill or gap, however
        many checks fired on it. Bills with no job form a group of their own."""
        wanted = ("resolved",) if filters.state == "done" else ACTIVE
        where = [Issue.status.in_(wanted)]
        if filters.owner:
            where.append(func.lower(Issue.owner) == filters.owner.lower())
        issues = list(await self.db.scalars(select(Issue).where(*where).options(*ITEM_PARTS)))
        items = await self._items_from(issues, await self._as_of())
        if filters.state in ("needs_action", "waiting"):
            items = [item for item in items if item.state == filters.state]
        if filters.state == "done":
            # An item with one check resolved and another still open is not done.
            still_open = await self._open_item_keys()
            items = [item for item in items if item.key not in still_open]

        jobs = {issue.job.job_number: issue.job for issue in issues if issue.job}
        groups = await self._reviewed(group_by_job(items, jobs), jobs)
        if filters.type:
            groups = [group for group in groups if any(filters.type in item.checks for item in group.items)]
        return ItemsResponse(groups=groups, item_count=sum(len(group.items) for group in groups))

    async def act_on_item(self, key: str, payload: ItemActionRequest) -> ItemResponse:
        """Do one thing to an item. It applies to every check behind it, so resolving a
        bill resolves all the issues that were about that bill. Recorded once in its history."""
        members = await self._item_issues(key)
        targets = [i for i in members if (i.status == "resolved") == (payload.action == "reopen") and i.status != "cleared"]
        if not targets:
            state = "open" if payload.action == "reopen" else "resolved"
            raise InvalidStateError(f"This is already {state}.")
        follow_up = payload.follow_up_on
        if follow_up is None and payload.follow_up_in_working_days:
            follow_up = working_days_from(await self._as_of() or date.today(), payload.follow_up_in_working_days)

        lead, others = targets[0], targets[1:]
        await apply_action(
            self.db, lead, payload.action, payload.actor, payload.note, payload.assignee, follow_up, payload.clear_follow_up
        )
        for other in others:
            # The same change, without a second entry in the history.
            other.owner, other.status, other.follow_up_on = lead.owner, lead.status, lead.follow_up_on
            other.resolution_note, other.dismissed = lead.resolution_note, lead.dismissed
        await self.db.commit()
        return await self.get_item(key)

    async def get_item(self, key: str) -> ItemResponse:
        return await self._pick(key, await self._item_issues(key), await self._as_of())

    async def review_job(self, job_number: str) -> JobItems:
        """Have the assistant review a job's open items: act, wait or dismiss for each, and
        which to deal with first. The review is kept until one of the items changes."""
        run = await self._current_run()
        job, fin = await self._job(job_number)
        issues = list(
            await self.db.scalars(select(Issue).where(Issue.job_id == job.id, Issue.status.in_(ACTIVE)).options(*ITEM_PARTS))
        )
        items = await self._items_from(issues, run.as_of)
        if not items:
            raise InvalidStateError("There is nothing open on this job to review.")
        about = {
            "name": job.name, "stage": job.stage, "contract_value": str(fin.contract_value),
            "ledger_revenue": str(fin.ledger_revenue), "ledger_cost": str(fin.ledger_cost), "ops_cost": str(fin.ops_cost),
            "owed_by_customer": str(fin.owed),
        }
        about["project_notes"] = await self._project_notes(job)
        answer = await self._with_model(review.review(about, items, run.as_of))

        await self.db.execute(delete(JobReview).where(JobReview.job_id == job.id))
        self.db.add(JobReview(job_id=job.id, fingerprint=fingerprint(items), payload=answer))
        await self.db.commit()
        return (await self._reviewed(group_by_job(items, {job.job_number: job}), {job.job_number: job}))[0]

    async def _project_notes(self, job: Job) -> list[dict]:
        """What the project team has written about the job in the project system."""
        project = select(SourceRecord.source_pk).where(SourceRecord.id == job.project_record_id).scalar_subquery()
        rows = await self.db.scalars(
            select(SourceRecord.payload)
            .where(SourceRecord.table_name == "project_notes", SourceRecord.payload["project_id"].astext == project)
            .order_by(SourceRecord.payload["created_at"].astext)
        )
        return [
            {"by": _person(payload.get("created_by_email")), "on": str(payload.get("created_at"))[:10], "note": payload.get("content")}
            for payload in rows
        ]

    async def _job_items(self, job: Job, as_of: date) -> JobItems | None:
        """One job's open items, with the assistant's review when there is a current one."""
        issues = list(
            await self.db.scalars(select(Issue).where(Issue.job_id == job.id, Issue.status.in_(ACTIVE)).options(*ITEM_PARTS))
        )
        if not issues:
            return None
        jobs = {job.job_number: job}
        return (await self._reviewed(group_by_job(await self._items_from(issues, as_of), jobs), jobs))[0]

    async def _reviewed(self, groups: list[JobItems], jobs: dict[str, Job]) -> list[JobItems]:
        """Lay each job's stored review over its items, when the items have not changed since."""
        ids = {jobs[group.job_number].id: group for group in groups if group.job_number in jobs}
        if not ids:
            return groups
        for stored in await self.db.scalars(select(JobReview).where(JobReview.job_id.in_(ids))):
            group = ids[stored.job_id]
            if stored.fingerprint != fingerprint(group.items):
                continue
            for item in group.items:
                entry = stored.payload["items"].get(item.key)
                if entry and item.state != "done":
                    item.suggestion = review.suggestion_for(item, entry)
            group.suggestion = review.first_from(stored.payload, group.items) or group.suggestion
            group.reviewed_at = stored.created_at
        return groups

    async def _open_item_keys(self) -> set[str]:
        issues = list(await self.db.scalars(select(Issue).where(Issue.status.in_(ACTIVE)).options(*ITEM_PARTS)))
        return {item.key for item in build_items(issues, None)}

    async def _item_issues(self, key: str) -> list[Issue]:
        """Every issue behind one item, whatever its status, from the item's name."""
        kind, _, subject = key.partition(":")
        if kind not in TITLES or not subject:
            raise ItemNotFoundError(key)
        if kind in DOCUMENT_KINDS:
            # The checks about the document itself, plus a closed job's check that cites it.
            on_same_job = select(Issue.job_id).where(Issue.document == subject, Issue.job_id.is_not(None))
            where = or_(Issue.document == subject, and_(Issue.type_key == "closed_bills", Issue.job_id.in_(on_same_job)))
        else:
            where = Issue.job_id.in_(select(Job.id).where(Job.job_number == subject.upper()))
        # Read afresh: an action just taken has added to the history.
        issues = list(
            await self.db.scalars(
                select(Issue).where(where, Issue.status != "cleared").options(*ITEM_PARTS).execution_options(populate_existing=True)
            )
        )
        members = [i for i in issues if KIND_OF[i.type_key] == kind]
        if not any(item.key == key for item in build_items(members, None)):
            raise ItemNotFoundError(key)
        return sorted(
            (i for i in members if key in {item.key for item in build_items([i], None)}),
            key=lambda i: (i.status not in ACTIVE, i.type.severity != "high", -i.amount, i.id),
        )

    async def _pick(self, key: str, members: list[Issue], as_of: date | None) -> ItemResponse:
        return next(item for item in await self._items_from(members, as_of) if item.key == key)

    async def _items_from(self, issues: list[Issue], as_of: date | None) -> list[ItemResponse]:
        """Group issues into items, and give each invoice the notes already written on it in accounting."""
        items = build_items(issues, as_of)
        numbers = [item.document for item in items if item.document and item.kind.startswith("invoice")]
        if not numbers:
            return items
        note, invoice = aliased(SourceRecord), aliased(SourceRecord)
        rows = await self.db.execute(
            select(invoice.payload["invoice_number"].astext, note.payload)
            .join(invoice, and_(invoice.table_name == "ar_invoices", invoice.source_pk == note.payload["invoice_id"].astext))
            .where(note.table_name == "ar_invoice_notes", invoice.payload["invoice_number"].astext.in_(numbers))
            .order_by(note.payload["created_at"].astext)
        )
        written: dict[str, list[SourceNote]] = defaultdict(list)
        for number, payload in rows:
            written[number].append(
                SourceNote(by=_person(payload.get("created_by_email")), on=str(payload.get("created_at"))[:10], note=payload.get("content") or "")
            )
        for item in items:
            item.source_notes = written.get(item.document or "", [])
        return items

    async def draft_for_item(self, key: str, payload: DraftRequest) -> DraftResponse:
        """Draft the message that the work on an item starts with. Who it goes to, what it
        asks for and every fact in it come from the records and fixed rules."""
        run = await self._current_run()
        item = await self._pick(key, await self._item_issues(key), run.as_of)
        if item.state == "done":
            raise InvalidStateError("This is already resolved, so there is nothing to follow up.")
        if item.action.key not in ("message_customer", "message_colleague"):
            raise InvalidRequestError(f"{item.title} is not fixed by sending a message.")
        status = next((line.status for line in item.evidence if line.doc_number == item.document), None)
        facts = {
            "problem": item.title,
            "what_is_wrong": item.details,
            "tags": [tag.label for tag in item.tags],
            "what_to_ask_for": what_to_ask(item.kind, status, item.document),
            "job": item.job_name,
            "job_number": item.job_number,
            "document": item.document,
            "amount": item.amount,
            "due_on": item.due_on,
            "days_late": item.days_late,
            "records": [
                {
                    "number": line.doc_number, "company": line.company, "amount": line.amount, "paid": line.paid_amount,
                    "unpaid": line.open_amount, "dated": line.line_date, "due": line.due_date, "status": line.status,
                }
                for line in item.evidence
                if line.kind in (INVOICE, BILL)
            ],
            "notes_so_far": [
                *({"by": note.by, "on": note.on, "note": note.note} for note in item.source_notes),
                *(
                    {"by": event.actor, "on": event.created_at.date(), "note": event.note}
                    for event in item.events
                    if event.kind == "commented"
                ),
            ],
        }
        facts = json.loads(json.dumps(facts, default=str))
        recipient = await self._recipient(item, status, payload.writer)
        return await self._with_model(drafts.write(facts, payload.writer, recipient, item.document, run.as_of))

    # --- Bill coding ---------------------------------------------------------------

    async def suggest_job_for_issue(self, issue_id: int) -> CodingResponse:
        """Suggest which job an unassigned vendor bill belongs to. The suggestion is
        recorded in the issue's history; accepting or rejecting it is the person's call."""
        issue = await self._issue(issue_id)
        if issue.type_key != "no_job" or not issue.evidence:
            raise InvalidRequestError("Only a vendor bill with no job can be coded.")
        if issue.status not in ACTIVE:
            raise InvalidStateError(f"A {issue.status} issue needs no coding. Reopen it first.")
        suggestion = await self.suggest_job(issue.evidence[0].money_line_id)

        said = {
            "job": f"Suggested job {suggestion.job_number} ({suggestion.job_name}), {suggestion.confidence} confidence",
            "not_a_job_cost": f"Suggested this is not a job cost, {suggestion.confidence} confidence",
            "unsure": "Could not tell which job this belongs to"
            + (f"; the closest is {suggestion.runner_up.job_number}" if suggestion.runner_up else ""),
        }[suggestion.decision]
        self.db.add(IssueEvent(issue_id=issue.id, kind="suggested", actor="assistant", note=f"{said}. {' '.join(suggestion.reasons)}"))
        await self.db.commit()
        return suggestion

    async def suggest_job(self, bill_line_id: int) -> CodingResponse:
        """Run the bill coder on one vendor bill, whether or not it already has a job.
        The agent is never shown that job, so a bill whose job is known can be used to score it."""
        return await self._with_model(coding.suggest(await self._coding_case(bill_line_id)))

    async def _coding_case(self, bill_line_id: int) -> CodingCase:
        """Everything the bill coder may look at for one bill. The bill's own job is left out."""
        bill = await self.db.scalar(
            select(MoneyLine).where(MoneyLine.id == bill_line_id, MoneyLine.kind == BILL).options(selectinload(MoneyLine.company))
        )
        if bill is None:
            raise InvalidRequestError(f"There is no vendor bill with id {bill_line_id}.")

        same_vendor = list(
            await self.db.scalars(
                select(MoneyLine)
                .where(MoneyLine.kind == BILL, MoneyLine.company_id == bill.company_id, MoneyLine.id != bill.id)
                .options(selectinload(MoneyLine.job))
                .order_by(MoneyLine.line_date, MoneyLine.id)
            )
        ) if bill.company_id else []

        # Each bill's lines, as the vendor wrote them.
        raw_line = SourceRecord
        described: dict[str, list[dict]] = defaultdict(list)
        for row in await self.db.execute(
            select(raw_line.payload)
            .where(
                raw_line.table_name == "ap_invoice_lines",
                raw_line.payload["invoice_id"].astext.in_([bill.source_pk, *(other.source_pk for other in same_vendor)]),
            )
            .order_by(raw_line.id)
        ):
            described[row.payload["invoice_id"]].append(
                {"description": row.payload.get("description"), "amount": str(row.payload.get("amount"))}
            )

        # The email the bill arrived on, found by its attachment or by its number in the subject.
        attachment, email = aliased(SourceRecord), aliased(SourceRecord)
        subject = await self.db.scalar(
            select(email.payload["subject"].astext)
            .where(
                email.table_name == "inbound_emails",
                or_(
                    email.payload["subject"].astext.ilike(f"%{bill.doc_number}%"),
                    email.source_pk.in_(
                        select(attachment.payload["inbound_email_id"].astext).where(
                            attachment.table_name == "inbound_email_attachments",
                            attachment.payload["filename"].astext.ilike(f"{bill.doc_number}.%"),
                        )
                    ),
                ),
            )
            .limit(1)
        ) if bill.doc_number else None

        jobs = list(await self.db.scalars(select(Job).options(selectinload(Job.customer)).order_by(Job.job_number)))
        by_id = {job.id: job for job in jobs}
        work: dict[str, dict] = {job.job_number: {"cost_entries": [], "vendor_bills": []} for job in jobs}
        for line in await self.db.scalars(
            select(MoneyLine)
            .where(MoneyLine.kind.in_(("ops_cost", BILL)), MoneyLine.job_id.is_not(None), MoneyLine.id != bill.id)
            .options(selectinload(MoneyLine.company))
            .order_by(MoneyLine.line_date, MoneyLine.id)
        ):
            entry = work[by_id[line.job_id].job_number]
            if line.kind == BILL:
                entry["vendor_bills"].append(
                    {"number": line.doc_number, "vendor": line.company.name if line.company else line.description, "dated": str(line.line_date), "amount": str(line.amount)}
                )
            else:
                entry["cost_entries"].append(
                    {"what": line.description, "category": line.cost_category, "dated": str(line.line_date), "amount": str(line.amount)}
                )

        day = lambda value: str(value) if value else None  # noqa: E731
        return CodingCase(
            bill={
                "number": bill.doc_number,
                "vendor": bill.company.name if bill.company else bill.description,
                "dated": day(bill.line_date),
                "amount": str(bill.amount),
                "lines": described.get(bill.source_pk, []),
                "email_subject": subject,
            },
            vendor_history=[
                {
                    "number": other.doc_number, "dated": day(other.line_date), "amount": str(other.amount),
                    "lines": described.get(other.source_pk, []),
                    "job_number": other.job.job_number if other.job else None,
                    "job_name": other.job.name if other.job else None,
                }
                for other in same_vendor
            ],
            jobs=[
                {
                    "job_number": job.job_number, "name": job.name, "customer": job.customer.name if job.customer else None,
                    "branch": job.branch, "kind_of_work": job.service_line, "stage": job.stage, "won_on": day(job.won_on),
                    "on_site_on": day(job.on_site_on), "completed_on": day(job.completed_on), "closed_on": day(job.closed_on),
                }
                for job in jobs
            ],
            work_by_job=work,
        )

    async def _recipient(self, item: ItemResponse, status: str | None, writer: str) -> Recipient:
        """Who a message about an item goes to. An unpaid invoice goes to the customer's
        billing contact. Everything else stays inside the company, to whoever the item is
        waiting on: the job's ops manager or finance. Nobody is written to about their own item."""
        if item.action.key == "message_customer" and item.job_number:
            company, contact = aliased(SourceRecord), aliased(SourceRecord)
            row = (
                await self.db.execute(
                    select(Company.name, contact.payload)
                    .select_from(Job)
                    .join(Company, Company.id == Job.customer_id)
                    .join(company, and_(company.table_name == "companies", company.source_pk == Company.source_id))
                    .join(
                        contact,
                        and_(contact.table_name == "contacts", contact.source_pk == company.payload["billing_contact_id"].astext),
                    )
                    .where(Job.job_number == item.job_number)
                )
            ).one_or_none()
            # The invoice names its own person. When that is not the billing contact, they are copied in.
            copied: list[Copied] = []
            invoice = next(iter((await self._raw_where("ar_invoices", "invoice_number", item.document or ""))), {})
            on_invoice = (await self._raw("contacts", [invoice.get("contact_id") or ""])).get(invoice.get("contact_id") or "")
            billing_id = row.payload.get("id") if row else None
            if on_invoice and on_invoice.get("id") != billing_id:
                copied.append(Copied(
                    name=" ".join(p for p in (on_invoice.get("first_name"), on_invoice.get("last_name")) if p),
                    role=f"Named on invoice {item.document}" + (f", {on_invoice['title']}" if on_invoice.get("title") else ""),
                    email=on_invoice.get("email"),
                ))
            if row:
                name = " ".join(part for part in (row.payload.get("first_name"), row.payload.get("last_name")) if part)
                return Recipient(
                    audience="customer", name=name or row.name,
                    role=f"Billing contact at {row.name}", email=row.payload.get("email"), cc=copied,
                )
            return Recipient(audience="customer", name="Accounts payable", role="The customer's payables desk", email=None, cc=copied)

        if item.kind in SCHEDULE_KINDS and item.job_number:
            people = dict(
                (await self.db.execute(
                    select(JobOwner.role, JobOwner)
                    .join(Job, Job.id == JobOwner.job_id)
                    .where(Job.job_number == item.job_number)
                )).all()
            )
            manager, executive = people.get("ops_manager"), people.get("account_executive")
            # The ops manager answers for the schedule. Written by the ops manager, it goes
            # to the account executive, who keeps the customer informed.
            if manager and manager.name.lower() != writer.lower():
                return Recipient(audience="internal", name=manager.name, role="The job's ops manager", email=manager.email)
            if executive and executive.name.lower() != writer.lower():
                return Recipient(
                    audience="internal", name=executive.name, role="The job's account executive, who keeps the customer informed",
                    email=executive.email,
                )
        finance = Recipient(audience="internal", name="Finance", role="Harborstone's finance team", email=None)
        on_the_job = item.owner != FINANCE_QUEUE
        writer_has_it = item.owner.lower() == writer.lower()
        # Waiting on the project team: write to whoever has it, unless that is the writer.
        # Waiting on finance: the project team writes to finance, and finance writes to the project team.
        to_owner = on_the_job and not writer_has_it and (with_whom(item.kind, status) == "ops" or not await self._on_a_job(writer))
        if not to_owner:
            return finance
        email = await self.db.scalar(select(JobOwner.email).where(JobOwner.name == item.owner).limit(1))
        roles = {"ops_manager": "the job's ops manager", "account_executive": "the job's account executive"}
        return Recipient(
            audience="internal", name=item.owner,
            role=f"Has this issue as {roles.get(item.owner_role, 'its assigned owner')}", email=email,
        )

    async def _on_a_job(self, person: str) -> bool:
        """Whether this person is an ops manager or account executive on any job. Finance is not."""
        return bool(await self.db.scalar(select(exists().where(func.lower(JobOwner.name) == person.lower()))))

    async def list_ask_history(self, asked_by: str, limit: int = 50) -> list[AskResponse]:
        """One person's conversation, oldest first, ending with the most recent exchange."""
        latest = await self.db.scalars(
            select(AskExchange).where(AskExchange.asked_by == asked_by).order_by(AskExchange.id.desc()).limit(limit)
        )
        return [ask_response(e) for e in reversed(latest.all())]

    async def clear_ask_history(self, asked_by: str) -> None:
        await self.db.execute(delete(AskExchange).where(AskExchange.asked_by == asked_by))
        await self.db.commit()

    async def _recent_conversation(self, asked_by: str) -> list[AskMessage]:
        """The last few exchanges, as the model needs them to follow "and the second one?"."""
        messages: list[AskMessage] = []
        for exchange in await self.list_ask_history(asked_by, limit=ASK_MEMORY):
            messages.append(AskMessage(role="user", content=exchange.question))
            messages.append(AskMessage(role="assistant", content=exchange.answer))
        return messages

    # --- Source records ----------------------------------------------------------

    async def get_operations(self) -> OperationsResponse:
        """Luis's questions, one list each: did urgent jobs start quickly, which jobs are waiting
        to start, how is each job in progress pacing, and who owns what."""
        run = await self._current_run()
        tolerance = await self.db.scalar(select(IssueType.tolerance).where(IssueType.key == "slow_start"))
        allowed = int(tolerance or 14)
        jobs = list(
            await self.db.execute(
                select(Job, JobFinancials)
                .join(JobFinancials, and_(JobFinancials.job_id == Job.id, JobFinancials.sync_run_id == run.id))
                .options(selectinload(Job.owners))
                .order_by(Job.job_number)
            )
        )
        days = lambda later, earlier: (later - earlier).days if later and earlier else None  # noqa: E731

        last_work = dict(
            (
                await self.db.execute(
                    select(MoneyLine.job_id, func.max(MoneyLine.line_date))
                    .where(MoneyLine.kind.in_(("ops_cost", BILL)), MoneyLine.job_id.is_not(None))
                    .group_by(MoneyLine.job_id)
                )
            ).all()
        )
        flagged: dict[int, set[str]] = defaultdict(set)
        for job_id, key in await self.db.execute(
            select(Issue.job_id, Issue.type_key).where(
                Issue.status.in_(ACTIVE), Issue.type_key.in_(("past_finish", "no_activity", "budget_burn"))
            )
        ):
            flagged[job_id].add(key)

        urgent, waiting, pace = [], [], []
        for job, fin in jobs:
            manager = owner_name(job, "ops_manager")
            if job.urgent_reason and job.stage not in ("WORK_NOT_STARTED", "CANCELLED"):
                win = days(job.on_site_on, job.won_on)
                urgent.append(UrgentStart(
                    job_number=job.job_number, name=job.name, urgent_reason=job.urgent_reason,
                    incident_on=job.incident_on, won_on=job.won_on, on_site_on=job.on_site_on,
                    days_damage_to_site=days(job.on_site_on, job.incident_on), days_win_to_site=win,
                    started_in_time=win is not None and win <= 1,
                ))
            if job.stage == "WORK_NOT_STARTED":
                wait = days(job.on_site_on or run.as_of, job.won_on)
                waiting.append(WaitingStart(
                    job_number=job.job_number, name=job.name, ops_manager=manager, urgent_reason=job.urgent_reason,
                    won_on=job.won_on, on_site_on=job.on_site_on, days_win_to_start=wait,
                    slow=wait is not None and wait > (1 if job.urgent_reason else allowed),
                ))
            if job.stage == "IN_PROGRESS":
                span = days(job.planned_finish_on, job.on_site_on)
                gone = days(run.as_of, job.on_site_on)
                cost = max(fin.ops_cost, fin.ledger_cost)
                pace.append(JobPace(
                    job_number=job.job_number, name=job.name, ops_manager=manager, on_site_on=job.on_site_on,
                    planned_finish_on=job.planned_finish_on,
                    time_gone_pct=round(Decimal(min(gone, span)) / span * 100, 1) if span and gone is not None else None,
                    budget_used_pct=round(cost / job.budget * 100, 1) if job.budget else None,
                    last_work_on=last_work.get(job.id),
                    flags=sorted(flagged.get(job.id, ())),
                ))
        # Most urgent first: the slowest to start, then the ones waiting longest, then the ones with most wrong.
        urgent.sort(key=lambda u: (u.started_in_time, -(u.days_damage_to_site or 0)))
        waiting.sort(key=lambda w: (not w.slow, -(w.days_win_to_start or 0)))
        pace.sort(key=lambda p: (-len(p.flags), -(p.budget_used_pct or 0) + (p.time_gone_pct or 0)))

        open_items = (await self.list_items(ItemFilters(state="open"))).groups
        loads: dict[str, dict] = defaultdict(lambda: defaultdict(int))
        for job, _ in jobs:
            name = owner_name(job, "ops_manager") or "None assigned"
            if job.stage == "IN_PROGRESS":
                loads[name]["jobs_in_progress"] += 1
            elif job.stage == "WORK_NOT_STARTED":
                loads[name]["jobs_not_started"] += 1
            else:
                loads[name].setdefault("jobs_in_progress", 0)  # listed even when nothing is active
        for group in open_items:
            if group.job_number is None:
                continue
            name = group.ops_manager or "None assigned"
            for item in group.items:
                loads[name]["open_items"] += 1
                loads[name]["needing_action"] += item.state == "needs_action"
                loads[name]["schedule_items"] += item.kind in SCHEDULE_KINDS
        owners = [OwnerLoad(name=name, **counts) for name, counts in loads.items()]
        owners.sort(key=lambda o: (o.name == "None assigned", -o.open_items, o.name))

        return OperationsResponse(
            as_of=run.as_of,
            urgent_rule="Mitigation work, or a job tied to a named catastrophe. The CRM has an urgency field, but it is empty on every record",
            start_tolerance_days=allowed,
            urgent=urgent, waiting=waiting, in_progress=pace, owners=owners,
        )

    async def get_finance(self) -> FinanceResponse:
        """The ledger's view across every job: revenue, cost and cash by month, where cost
        went by cost code, how late receivables are, and profit by kind of work."""
        run = await self._current_run()
        line = MoneyLine
        on_a_job = line.job_id.in_(select(JobFinancials.job_id).where(JobFinancials.sync_run_id == run.id))

        def of(kind: str):
            return total_of(line.amount, line.kind == kind)

        def by(period):
            return (
                select(period.label("period"), of("ledger_revenue"), of("ledger_cost"), of(INVOICE), of("customer_payment"))
                .where(line.kind.in_(("ledger_revenue", "ledger_cost", INVOICE, "customer_payment")), line.line_date.is_not(None), on_a_job)
                .group_by(period)
                .order_by(period)
            )

        def running(periods: list[tuple]) -> list[dict]:
            """Each period's four figures, with the totals so far beside them."""
            so_far = [ZERO, ZERO, ZERO, ZERO]
            rows = []
            for key, *figures in periods:
                so_far = [total + figure for total, figure in zip(so_far, figures)]
                rows.append({
                    "key": key,
                    **dict(zip(("revenue", "cost", "invoiced", "collected"), figures)),
                    **dict(zip(("revenue_to_date", "cost_to_date", "invoiced_to_date", "collected_to_date"), so_far)),
                })
            return rows

        months = [
            FinanceMonth(month=row.pop("key"), **row)
            for row in running((await self.db.execute(by(func.to_char(line.line_date, "YYYY-MM")))).all())
        ]
        posted = {
            week: tuple(totals)
            for week, *totals in await self.db.execute(by(cast(func.date_trunc("week", line.line_date), Date)))
        }
        # Every week from the first to the last is shown, so a quiet week reads as zero, not as a gap.
        every_week = []
        if posted:
            week = min(posted)
            while week <= max(posted):
                every_week.append((week, *posted.get(week, (ZERO, ZERO, ZERO, ZERO))))
                week += timedelta(days=7)
        weeks = [FinanceWeek(week_of=row.pop("key"), **row) for row in running(every_week)]
        codes = await self.db.execute(
            select(line.cost_category, total_of(line.amount))
            .where(line.kind == "ops_cost", line.cost_category.is_not(None), on_a_job)
            .group_by(line.cost_category)
            .order_by(total_of(line.amount).desc())
        )
        codes = codes.all()
        logged = sum((amount for _, amount in codes), ZERO)
        accounts = await self.db.scalars(
            select(line.description).where(line.kind == "ledger_cost", on_a_job).distinct().order_by(line.description)
        )

        days_late = run.as_of - line.due_date
        bucket = case(
            (or_(line.due_date.is_(None), line.due_date >= run.as_of), "not_due"),
            (days_late <= 30, "late_1_30"),
            (days_late <= 60, "late_31_60"),
            else_="late_over_60",
        )
        unpaid = line.amount - line.paid_amount
        aged = {
            key: (count, amount)
            for key, count, amount in await self.db.execute(
                select(bucket, func.count(), total_of(unpaid))
                .where(line.kind == INVOICE, line.status == "SENT", unpaid > 0)
                .group_by(bucket)
            )
        }

        fin = JobFinancials
        kinds = await self.db.execute(
            select(Job.service_line, func.count(), total_of(fin.ledger_revenue), total_of(fin.ledger_cost))
            .join(fin, fin.job_id == Job.id)
            .where(fin.sync_run_id == run.id)
            .group_by(Job.service_line)
            .order_by(total_of(fin.ledger_revenue).desc())
        )
        by_kind = [
            WorkKindProfit(
                service_line=kind or "UNKNOWN", jobs=jobs, revenue=revenue, cost=cost,
                profit=revenue - cost, margin_pct=margin_pct(revenue, cost),
            )
            for kind, jobs, revenue, cost in kinds
        ]
        revenue = sum((kind.revenue for kind in by_kind), ZERO)
        cost = sum((kind.cost for kind in by_kind), ZERO)
        return FinanceResponse(
            as_of=run.as_of,
            revenue=revenue,
            cost=cost,
            profit=revenue - cost,
            margin_pct=margin_pct(revenue, cost),
            by_month=months,
            by_week=weeks,
            cost_by_code=[CostByCode(cost_code=code, ops_cost=amount, share_pct=share_pct(amount, logged)) for code, amount in codes],
            logged_cost=logged,
            ledger_cost_accounts=[text.removeprefix("Account ") for text in accounts if text],
            receivables_by_age=[
                ReceivableAge(bucket=key, invoices=aged.get(key, (0, ZERO))[0], amount=aged.get(key, (0, ZERO))[1])
                for key in ("not_due", "late_1_30", "late_31_60", "late_over_60")
            ],
            by_service_line=by_kind,
        )

    async def get_document(self, line_id: int) -> DocumentResponse:
        """An invoice or vendor bill laid out from its records: who it is from and to, its
        lines, totals and payments. Built from the copied source rows, not the original file."""
        line = await self.db.scalar(
            select(MoneyLine)
            .where(MoneyLine.id == line_id, MoneyLine.kind.in_((INVOICE, BILL)))
            .options(selectinload(MoneyLine.job), selectinload(MoneyLine.company))
        )
        if line is None:
            raise SourceRecordNotFoundError(line_id)
        rows = await self._raw(line.source_table, [line.source_pk])
        doc = rows.get(line.source_pk, {})

        invoice = line.kind == INVOICE
        child = "ar_invoice_lines" if invoice else "ap_invoice_lines"
        parts = [p for p in await self._raw_where(child, "invoice_id", line.source_pk)]
        payments = await self._raw_where("ar_payments", "invoice_id", line.source_pk) if invoice else []

        entities = await self._raw("legal_entities", [doc.get("legal_entity_id") or ""])
        entity = entities.get(doc.get("legal_entity_id") or "")
        us = DocumentParty(
            # Three bills carry no legal entity. Say so, rather than guess which company was billed.
            name=(entity or {}).get("legal_name") or (entity or {}).get("name") or "No legal entity on record",
            address=await self._address((entity or {}).get("billing_address_id")),
        )

        company_id = (line.company.source_id if line.company else None) or doc.get("company_id") or doc.get("vendor_id")
        company = (await self._raw("companies", [company_id or ""])).get(company_id or "", {})
        contact_id = doc.get("contact_id") if invoice else doc.get("vendor_contact_id")
        contact = (await self._raw("contacts", [contact_id or ""])).get(contact_id or "", {})
        them = DocumentParty(
            name=company.get("name") or (line.company.name if line.company else doc.get("vendor_name") or "Unknown"),
            attention=" ".join(p for p in (contact.get("first_name"), contact.get("last_name")) if p) or None,
            title=contact.get("title"), email=contact.get("email"),
            address=await self._address(company.get("address_id")),
        )

        site: list[str] = []
        if line.job:
            opportunity = (await self._raw("opportunities", [doc.get("opportunity_id") or ""])).get(doc.get("opportunity_id") or "", {})
            site = await self._address(opportunity.get("address_id"))

        issued, due = to_day(doc.get("invoice_date")), to_day(doc.get("due_date"))
        terms = f"Net {(due - issued).days}" if issued and due else None
        discount = None
        if not invoice and company_id:
            for term in await self._raw_where("vendor_discount_terms", "company_id", company_id):
                deadline = issued + timedelta(days=int(term["discount_days"])) if issued else None
                discount = (
                    f"{Decimal(str(term['discount_percentage'])).normalize()}% off if paid within {term['discount_days']} days"
                    + (f", by {deadline:%d %B %Y}" if deadline else "")
                )

        files: list[str] = []
        received = None
        if invoice:
            for link in await self._raw_where("ar_invoice_documents", "invoice_id", line.source_pk):
                files.append(f"{(link.get('document_type') or 'Document').title()} PDF")
        elif line.doc_number:
            attachment = aliased(SourceRecord)
            mail = (
                await self.db.execute(
                    select(SourceRecord.payload, attachment.payload)
                    .outerjoin(
                        attachment,
                        and_(attachment.table_name == "inbound_email_attachments", attachment.payload["inbound_email_id"].astext == SourceRecord.source_pk),
                    )
                    .where(
                        SourceRecord.table_name == "inbound_emails",
                        or_(
                            SourceRecord.payload["subject"].astext.ilike(f"%{line.doc_number}%"),
                            attachment.payload["filename"].astext.ilike(f"{line.doc_number}.%"),
                        ),
                    )
                    .limit(1)
                )
            ).first()
            if mail:
                email, file = mail
                received = f"Emailed by {email.get('from_email')} on {str(email.get('received_at'))[:10]}: {email.get('subject')}"
                if file:
                    files.append(file.get("filename"))

        def money_of(value) -> Decimal:
            return Decimal(str(value)) if value not in (None, "") else ZERO

        total = money_of(doc.get("total") if invoice else doc.get("amount")) or line.amount
        tax = money_of(doc.get("tax_amount"))
        paid = line.paid_amount
        notes = [n.get("content") for n in await self._raw_where("ar_invoice_notes", "invoice_id", line.source_pk)] if invoice else []
        if doc.get("notes"):
            notes.insert(0, doc["notes"])

        return DocumentResponse(
            line_id=line.id,
            kind=line.kind,
            number=line.doc_number or "",
            status=line.status,
            issued_on=issued, due_on=due,
            approved_on=to_day(doc.get("approval_date")), sent_on=to_day(doc.get("sent_date")),
            terms=terms, discount=discount,
            issuer=us if invoice else them,
            recipient=them if invoice else us,
            job_number=line.job.job_number if line.job else None,
            job_name=line.job.name if line.job else None,
            site=site,
            lines=[
                DocumentLine(
                    description=p.get("description") or "",
                    quantity=Decimal(str(p["quantity"])) if p.get("quantity") is not None else None,
                    unit_price=money_of(p.get("unit_price")) if p.get("unit_price") is not None else None,
                    amount=money_of(p.get("amount")),
                )
                for p in parts
            ],
            subtotal=money_of(doc.get("subtotal")) or total - tax,
            tax=tax, total=total, paid=paid, balance=total - paid,
            payments=[
                DocumentPayment(
                    on=to_day(p.get("payment_date")), amount=money_of(p.get("amount")),
                    method=p.get("payment_method"), reference=p.get("reference_number"),
                )
                for p in sorted(payments, key=lambda p: str(p.get("payment_date")))
            ],
            files=files, received_by_email=received, notes=[n for n in notes if n],
            source_record_id=line.source_record_id,
        )

    async def _raw(self, table: str, keys: list[str]) -> dict[str, dict]:
        """Copied source rows from one table, by their key in the source system."""
        found = await self.db.execute(
            select(SourceRecord.source_pk, SourceRecord.payload).where(SourceRecord.table_name == table, SourceRecord.source_pk.in_(keys))
        )
        return dict(found.all())

    async def _raw_where(self, table: str, field: str, value: str) -> list[dict]:
        found = await self.db.scalars(
            select(SourceRecord.payload)
            .where(SourceRecord.table_name == table, SourceRecord.payload[field].astext == value)
            .order_by(SourceRecord.id)
        )
        return list(found)

    async def _address(self, address_id: str | None) -> list[str]:
        """An address as the lines it is printed on."""
        found = (await self._raw("addresses", [address_id or ""])).get(address_id or "")
        if not found:
            return []
        street = ", ".join(p for p in (found.get("street_address"), found.get("unit")) if p)
        town = " ".join(p for p in (f"{found.get('city')}," if found.get("city") else None, found.get("state"), found.get("zip_code")) if p)
        return [p for p in (street, town) if p]

    async def list_sources(self) -> list[SourceSystem]:
        """The three systems the figures come from, with how much of each we hold and when it was last read."""
        last_read = await self.db.scalar(
            select(SyncRun.finished_at).where(SyncRun.status == "succeeded").order_by(SyncRun.id.desc()).limit(1)
        )
        rows = await self.db.execute(
            select(SourceRecord.system, func.count(SourceRecord.table_name.distinct()), func.count())
            .where(SourceRecord.system.in_(("crm", "project", "accounting")))
            .group_by(SourceRecord.system)
        )
        found = {system: (tables, records) for system, tables, records in rows}
        return [
            SourceSystem(system=system, tables=found.get(system, (0, 0))[0], records=found.get(system, (0, 0))[1], last_read_at=last_read)
            for system in ("crm", "project", "accounting")
        ]

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
            .options(*ISSUE_PARTS)
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

    async def _as_of(self) -> date | None:
        """The date of the latest sync, or None before the first one."""
        run_id = await latest_run_id(self.db)
        return (await self.db.get(SyncRun, run_id)).as_of if run_id else None

    async def _issue_detail(self, issue_id: int) -> IssueDetailResponse:
        issue = await self._issue(issue_id)
        related: list[Issue] = []
        if issue.document:
            # The other open issues about the same invoice or bill, largest first.
            related = list(
                await self.db.scalars(
                    select(Issue)
                    .where(Issue.document == issue.document, Issue.id != issue.id, Issue.status.in_(ACTIVE))
                    .options(*ISSUE_PARTS)
                    .order_by(Issue.amount.desc(), Issue.key)
                )
            )
        return issue_detail_response(issue, await self._as_of(), related)

    async def _issue(self, issue_id: int) -> Issue:
        evidence_line = selectinload(Issue.evidence).selectinload(IssueEvidence.line)
        query = (
            select(Issue)
            .where(Issue.id == issue_id)
            .options(
                *ISSUE_PARTS,
                selectinload(Issue.events),
                # The same job is reached twice, so both paths load the people on it.
                evidence_line.selectinload(MoneyLine.job).selectinload(Job.owners),
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
