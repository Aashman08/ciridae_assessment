"""Request validation and public response contracts. Money serializes as strings."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, model_validator

from app.financials import CostBasis, RevenueBasis

CENT = Decimal("0.01")

# Dollars and cents as a string, e.g. "246300.00". Floats cannot hold most
# cent amounts exactly, so money never travels as a JSON number.
Money = Annotated[
    Decimal, PlainSerializer(lambda v: format(v.quantize(CENT), "f"), return_type=str, when_used="json")
]
Percent = Annotated[Decimal, PlainSerializer(lambda v: format(v, "f"), return_type=str, when_used="json")]
# A tolerance prints without trailing zeros ("0.02", "1"), however it was stored.
Tolerance = Annotated[
    Decimal, PlainSerializer(lambda v: format(v.normalize(), "f"), return_type=str, when_used="json")
]

T = TypeVar("T")


class ListResponse(BaseModel, Generic[T]):
    data: list[T]
    total: int = Field(description="How many match the filters, before paging")
    has_more: bool


class ErrorBody(BaseModel):
    type: str
    message: str
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorBody


# --- Filters -------------------------------------------------------------------


class Paging(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(50, ge=1, le=500)
    offset: int = Field(0, ge=0)


class JobFilters(Paging):
    stage: str | None = Field(None, description="WORK_NOT_STARTED, IN_PROGRESS, COMPLETED, CLOSED or CANCELLED")
    owner: str | None = Field(None, description="Ops manager's name")
    branch: str | None = None
    has_issues: bool | None = None
    q: str | None = Field(None, max_length=120, description="Part of a job number, job name or customer name")
    sort: Literal[
        "issues", "job_number", "name", "contract", "revenue", "cost", "profit", "margin", "planned_margin", "owed"
    ] = Field("issues", description="profit and margin use ledger revenue and ledger cost")
    order: Literal["asc", "desc"] = "desc"


class LineFilters(Paging):
    kind: str = Field(description="customer_invoice, vendor_bill, or any other money line kind")
    owner: str | None = Field(None, description="Limit to one ops manager's jobs")
    no_job: bool | None = Field(None, description="True for lines with no job assigned, false for lines with one")
    status: str | None = Field(None, description="Only lines with this source status, such as SENT or NEEDS_REVIEW")
    balance: Literal["open", "past_due"] | None = Field(
        None, description="open: still has an amount unpaid. past_due: a sent invoice unpaid after its due date"
    )


class IssueFilters(Paging):
    type: str | None = Field(None, description="Issue type key, such as past_due")
    owner: str | None = None
    status: str = Field("active", description="active (open or assigned), open, assigned, resolved, cleared or all")
    severity: Literal["high", "medium"] | None = None
    job: str | None = Field(None, description="Job number")
    sort: Literal["amount", "severity", "due", "follow_up", "owner"] = "amount"
    order: Literal["asc", "desc"] = "desc"


# --- Sync runs -----------------------------------------------------------------


class SyncRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of: date | None = Field(
        None,
        description="Date that past-due and deadline checks are measured against. Defaults to the export date.",
    )


class SyncRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    as_of: date
    started_at: datetime
    finished_at: datetime | None
    stats: dict
    error: str | None


# --- Money lines ---------------------------------------------------------------


class LineResponse(BaseModel):
    id: int
    kind: str
    doc_number: str | None
    description: str | None
    job_number: str | None
    company: str | None
    amount: Money
    paid_amount: Money
    open_amount: Money
    line_date: date | None
    due_date: date | None
    status: str | None
    cost_category: str | None
    source_table: str
    source_record_id: int


# --- Documents -----------------------------------------------------------------


class DocumentParty(BaseModel):
    name: str
    attention: str | None = Field(None, description="The person the document is addressed to")
    title: str | None = None
    email: str | None = None
    address: list[str] = Field(default_factory=list, description="Address lines, top to bottom")


class DocumentLine(BaseModel):
    description: str
    quantity: Decimal | None
    unit_price: Money | None
    amount: Money


class DocumentPayment(BaseModel):
    on: date | None
    amount: Money
    method: str | None
    reference: str | None


class DocumentResponse(BaseModel):
    """An invoice or vendor bill laid out from its records, as the paper copy would be.
    Built from the source rows; it is not the original PDF."""

    line_id: int
    kind: Literal["customer_invoice", "vendor_bill"]
    number: str
    status: str | None
    issued_on: date | None
    due_on: date | None
    approved_on: date | None = None
    sent_on: date | None = None
    terms: str | None = Field(description="Payment terms in words, worked out from the dates")
    discount: str | None = Field(None, description="An early-payment discount the vendor offers, in words")
    issuer: DocumentParty
    recipient: DocumentParty
    job_number: str | None
    job_name: str | None
    site: list[str] = Field(default_factory=list, description="The job site's address")
    lines: list[DocumentLine]
    subtotal: Money
    tax: Money
    total: Money
    paid: Money
    balance: Money
    payments: list[DocumentPayment]
    files: list[str] = Field(description="Files held for this document, by name")
    received_by_email: str | None = Field(None, description="For a bill: who emailed it and the subject")
    notes: list[str]
    source_record_id: int


# --- Issues --------------------------------------------------------------------


class IssueResponse(BaseModel):
    id: int
    key: str
    type_key: str
    title: str
    severity: str
    about: str
    job_number: str | None
    job_name: str | None
    subject: str
    document: str | None = Field(description="The invoice or bill this is about. None for job-level issues")
    due_on: date | None = Field(description="The date something has to happen by, when there is one")
    amount: Money
    summary: str
    detail: str
    next_step: str
    action_label: str
    owner: str
    owner_role: Literal["ops_manager", "account_executive", "finance", "assigned"] = Field(
        description="Why this person has it: the job's ops manager, its account executive because there is no "
        "ops manager, the finance queue because there is neither, or because someone assigned it to them"
    )
    status: str
    resolution_note: str | None
    note_count: int = Field(description="How many notes people have left on this issue")
    follow_up_on: date | None = Field(description="A date someone set to come back to this")
    days_late: int | None = Field(description="Days past `due_on` as of the sync date. None when not yet due or no due date")
    same_document: int = Field(description="Other open issues about the same invoice or bill. It is the same money")
    first_seen_on: date
    first_seen_run_id: int
    last_seen_run_id: int
    updated_at: datetime


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    actor: str
    note: str | None
    created_at: datetime


class RelatedIssue(BaseModel):
    id: int
    title: str
    severity: str
    amount: Money


class IssueDetailResponse(IssueResponse):
    evidence: list[LineResponse]
    events: list[EventResponse]
    related: list[RelatedIssue] = Field(description="Other open issues about the same invoice or bill")


class IssueAction(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    action: Literal["update", "assign", "comment", "resolve", "reopen"] = Field(
        description="update saves any of a note, a new owner and a follow-up date together"
    )
    actor: str = Field(min_length=1, max_length=120, description="Who is doing this")
    note: str | None = None
    assignee: str | None = Field(None, max_length=120)
    follow_up_on: date | None = Field(None, description="With update: a date to come back to this")
    clear_follow_up: bool = Field(False, description="With update: remove the follow-up date")


class PersonResponse(BaseModel):
    """Someone an issue can belong to."""

    name: str
    roles: list[str] = Field(description="ops_manager, account_executive or finance")


class IssueTypeResponse(BaseModel):
    key: str
    title: str
    severity: str
    about: str
    description: str
    enabled: bool
    tolerance: Tolerance | None
    tolerance_unit: str | None
    open_count: int
    open_amount: Money
    origin: Literal["built_in", "rule", "reading"] = Field(
        "built_in", description="built_in: written in code. rule: added by a person, run as a rule. reading: added by a person, read by the assistant"
    )
    subject: str | None = Field(None, description="For a check a person added: job, customer_invoice or vendor_bill")
    created_by: str | None = None


class IssueTypeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    tolerance: Decimal | None = Field(None, ge=0)
    actor: str = Field("Someone", min_length=1, max_length=120, description="Who is making the change, for the activity log")


# --- Activity ------------------------------------------------------------------

ActivitySource = Literal["project", "accounting", "app"]


class ActivityFilters(Paging):
    job: str | None = Field(None, description="Only this job, by job number")
    owner: str | None = Field(None, description="Only jobs this person is the ops manager of")
    person: str | None = Field(None, description="Only what this person did or wrote. 'system' is a sync, 'assistant' the assistant")
    source: ActivitySource | None = Field(
        None, description="project: notes in the project system. accounting: notes in accounting. app: what people did in this app"
    )
    kind: str | None = Field(
        None, description="note, or what happened to an issue: opened, assigned, follow_up, commented, suggested, resolved, "
        "dismissed, reopened, cleared. setting_changed for a change to a check"
    )
    people_only: bool = Field(False, description="Leave out what syncs did, so only what people wrote or did remains")


class ActivityEntry(BaseModel):
    """One note or one action, newest first in any list of them."""

    at: datetime
    source: ActivitySource
    kind: str
    by: str = Field(description="A person's name, or 'system' for a sync and 'assistant' for the assistant")
    text: str | None = Field(None, description="The note itself, or what was said or changed")
    about: str | None = Field(None, description="The check it concerns, such as Past due")
    job_number: str | None = None
    job_name: str | None = None
    document: str | None = Field(None, description="The invoice or bill it concerns")


# --- Jobs ----------------------------------------------------------------------


class TopIssue(BaseModel):
    type_key: str
    title: str
    amount: Money


class JobSummaryResponse(BaseModel):
    job_number: str
    name: str
    customer: str | None
    stage: str
    branch: str | None
    service_line: str | None
    ops_manager: str | None
    account_executive: str | None
    contract_value: Money
    budget: Money
    planned_margin_pct: Percent | None
    ledger_profit: Money = Field(description="Ledger revenue less ledger cost")
    ledger_margin_pct: Percent | None = Field(description="Ledger profit as a share of ledger revenue. None with no revenue")
    ledger_revenue: Money
    invoiced: Money
    sent: Money
    collected: Money
    owed: Money
    past_due: Money
    ops_cost: Money
    ledger_cost: Money
    unpaid_bills: Money
    issue_count: int
    top_issue: TopIssue | None


class FigureOption(BaseModel):
    basis: str
    label: str
    description: str
    amount: Money


class ProfitResponse(BaseModel):
    revenue_basis: RevenueBasis
    cost_basis: CostBasis
    revenue: Money
    cost: Money
    profit: Money
    margin_pct: Percent | None
    planned_margin_pct: Percent | None


class JobDetailResponse(JobSummaryResponse):
    estimated_value: Money | None
    original_contract_value: Money | None
    won_on: date | None
    on_site_on: date | None
    planned_finish_on: date | None
    completed_on: date | None
    closed_on: date | None
    cancelled_on: date | None
    crm_status: str | None
    revenue_options: list[FigureOption]
    cost_options: list[FigureOption]
    profit: ProfitResponse
    issues: list[IssueResponse]
    invoices: list[LineResponse]
    vendor_bills: list[LineResponse]
    items: "JobItems | None" = Field(None, description="What needs fixing on this job, one item per invoice, bill or gap")


# --- Summary -------------------------------------------------------------------


class CashSummary(BaseModel):
    owed: Money
    past_due: Money
    invoices_not_sent: Money
    invoices_not_sent_count: int
    vendor_bills_unpaid: Money
    vendor_bills_count: int
    invoice_count: int


class ContractStage(BaseModel):
    key: Literal["collected", "sent_not_collected", "invoiced_not_sent", "earned_not_invoiced", "not_yet_earned"]
    amount: Money
    share_pct: Percent = Field(description="This part as a share of the contract value")


class ContractToCash(BaseModel):
    contract_value: Money
    earned: Money
    invoiced: Money
    sent: Money
    collected: Money
    stages: list[ContractStage] = Field(
        description="The contract value split by how far it has got: each part has reached one stage and not the next"
    )


class IssuesByType(BaseModel):
    type_key: str
    title: str
    severity: str
    count: int
    amount: Money


class CountedOnce(BaseModel):
    count: int
    amount: Money


class SummaryResponse(BaseModel):
    sync_run_id: int
    as_of: date
    owner: str | None
    job_count: int
    cash: CashSummary
    contract_to_cash: ContractToCash
    open_issue_count: int = Field(description="How many checks have fired and are still open")
    open_item_count: int = Field(description="How many things there are to fix. Several checks on one invoice or bill count once")
    jobs_with_issues: int
    issues_by_type: list[IssuesByType]
    flagged_documents: CountedOnce = Field(
        description="The invoices and bills with at least one open issue, each counted once however many issues name it, "
        "and what is unpaid on them"
    )


# --- Operations ----------------------------------------------------------------


class UrgentStart(BaseModel):
    job_number: str
    name: str
    urgent_reason: str
    incident_on: date | None
    won_on: date | None
    on_site_on: date | None
    days_damage_to_site: int | None = Field(description="From the date of the damage to the first day on site")
    days_win_to_site: int | None
    started_in_time: bool = Field(description="On site within a day of being won")


class WaitingStart(BaseModel):
    job_number: str
    name: str
    ops_manager: str | None
    urgent_reason: str | None
    won_on: date | None
    on_site_on: date | None = Field(description="The planned first day on site. None if no date is set")
    days_win_to_start: int | None
    slow: bool = Field(description="Starting later after the win than the tolerance allows")


class JobPace(BaseModel):
    job_number: str
    name: str
    ops_manager: str | None
    on_site_on: date | None
    planned_finish_on: date | None
    time_gone_pct: Percent | None = Field(description="Share of the time from first day on site to planned finish that has gone")
    budget_used_pct: Percent | None = Field(description="Cost so far, the higher of ops log and ledger, as a share of budget")
    last_work_on: date | None = Field(description="The latest cost entry or vendor bill on the job")
    flags: list[Literal["past_finish", "no_activity", "budget_burn"]]


class OwnerLoad(BaseModel):
    name: str = Field(description="The ops manager, or None assigned")
    jobs_in_progress: int = 0
    jobs_not_started: int = 0
    open_items: int = 0
    needing_action: int = 0
    schedule_items: int = Field(0, description="Of the open items, how many are about starting, stalling or spending ahead")


class OperationsResponse(BaseModel):
    """Whether jobs start quickly, keep moving, spend at the right pace, and have someone in charge."""

    as_of: date
    urgent_rule: str
    start_tolerance_days: int
    urgent: list[UrgentStart]
    waiting: list[WaitingStart]
    in_progress: list[JobPace]
    owners: list[OwnerLoad]


# --- Finance -------------------------------------------------------------------


class FinancePeriod(BaseModel):
    """What happened in one week or month, and the running total from the first period to this one."""

    revenue: Money = Field(description="Revenue posted to the ledger")
    cost: Money = Field(description="Job cost posted to the ledger")
    invoiced: Money = Field(description="Customer invoices dated in the period")
    collected: Money = Field(description="Customer payments received")
    revenue_to_date: Money
    cost_to_date: Money
    invoiced_to_date: Money
    collected_to_date: Money


class FinanceMonth(FinancePeriod):
    month: str = Field(description="The calendar month, as YYYY-MM")


class FinanceWeek(FinancePeriod):
    week_of: date = Field(description="The Monday the week starts on")


class CostByCode(BaseModel):
    cost_code: str
    ops_cost: Money = Field(description="What the project team logged under this cost code")
    share_pct: Percent = Field(description="Its share of all cost the project teams logged")


class ReceivableAge(BaseModel):
    bucket: Literal["not_due", "late_1_30", "late_31_60", "late_over_60"]
    invoices: int
    amount: Money


class WorkKindProfit(BaseModel):
    service_line: str
    jobs: int
    revenue: Money
    cost: Money
    profit: Money
    margin_pct: Percent | None


class FinanceResponse(BaseModel):
    """The ledger's view of the business: what was earned and spent, where cost went, and what is owed."""

    as_of: date
    revenue: Money
    cost: Money
    profit: Money
    margin_pct: Percent | None
    by_month: list[FinanceMonth]
    by_week: list[FinanceWeek] = Field(description="The same figures a week at a time, with a zero for a week with nothing posted")
    cost_by_code: list[CostByCode]
    logged_cost: Money = Field(description="All cost the project teams logged, the total of cost_by_code")
    ledger_cost_accounts: list[str] = Field(
        description="The ledger accounts job cost is posted to. One account means the ledger cannot split cost by cost code"
    )
    receivables_by_age: list[ReceivableAge]
    by_service_line: list[WorkKindProfit]


class SourceSystem(BaseModel):
    """One of Harborstone's systems, as we last read it."""

    system: Literal["crm", "project", "accounting"]
    tables: int = Field(description="How many of its tables we read")
    records: int = Field(description="How many of its rows we hold a copy of")
    last_read_at: datetime | None = Field(description="When the last sync that read it finished")


# --- Source records ------------------------------------------------------------


class SourceRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    system: str
    table_name: str
    source_pk: str
    payload: dict
    content_hash: str
    first_seen_run_id: int
    last_changed_run_id: int
    last_seen_run_id: int


# --- Customers -----------------------------------------------------------------


class MonthTotal(BaseModel):
    """What was invoiced or billed in one calendar month."""

    month: str = Field(description="The calendar month, as YYYY-MM")
    count: int
    amount: Money
    paid: Money
    unpaid: Money
    sent: Money = Field(description="Customer invoices only: the amount on invoices that have been sent")


class CustomerBalance(BaseModel):
    customer: str
    open_invoice_count: int = Field(description="Invoices with a balance still owed")
    owed: Money
    past_due: Money


# --- Ask -----------------------------------------------------------------------


class AskMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class AskPage(BaseModel):
    """What the person has on screen when they ask, so "this job" means something.
    It only points at things. The tools still decide what the person may see."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["overview", "jobs", "job", "issues", "issue", "invoices", "bills", "issue_types"]
    job_number: str | None = Field(None, pattern=r"^[A-Za-z0-9]{1,20}$")
    issue_id: int | None = Field(None, ge=1)
    filters: dict[str, str] = Field(default_factory=dict, description="The list filters in force, such as status or type")

    @model_validator(mode="after")
    def filters_are_small(self) -> "AskPage":
        if len(self.filters) > 8 or any(len(k) > 20 or len(v) > 60 for k, v in self.filters.items()):
            raise ValueError("too many filters, or a filter that is too long")
        return self


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=1000)
    page: AskPage | None = Field(None, description="The page the person is asking from")
    asked_by: str = Field("anonymous", min_length=1, max_length=120, description="Who is asking. Their conversation is kept under this name")
    owner: str | None = Field(None, description="Limit every answer to one ops manager's jobs")


class AskSource(BaseModel):
    kind: Literal["job", "issue", "invoice", "vendor_bill"]
    id: str = Field(description="Job number for a job, invoice or bill; issue id for an issue")
    label: str


class AskStep(BaseModel):
    tool: str
    arguments: dict


class AskText(BaseModel):
    """A sentence or short paragraph."""

    type: Literal["text"]
    text: str = Field(min_length=1)


class AskColumn(BaseModel):
    label: str
    kind: Literal["text", "money", "number", "date"] = Field(description="What the column holds, which decides how it is set")


class AskTable(BaseModel):
    """Several records with the same facts about each: one record per row, one fact per column."""

    type: Literal["table"]
    columns: list[AskColumn] = Field(min_length=1)
    rows: list[list[str]] = Field(description="One list per row, with one value for each column, in column order")

    @model_validator(mode="after")
    def rows_match_columns(self) -> "AskTable":
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("every row needs exactly one value for each column")
        return self


class AskFigure(BaseModel):
    label: str
    value: str


class AskFigures(BaseModel):
    """A few headline figures, each with a short label."""

    type: Literal["figures"]
    items: list[AskFigure] = Field(min_length=1)


class AskSeries(BaseModel):
    label: str
    values: list[float] = Field(description="One value for each point along the bottom, in order")


class AskChart(BaseModel):
    """A line or bar chart: one or more series of numbers over the same ordered points."""

    type: Literal["chart"]
    kind: Literal["line", "bar"]
    title: str
    unit: Literal["money", "number", "percent"] = Field(description="What the values are, which decides how they are written")
    points: list[str] = Field(min_length=2, description="The labels along the bottom, such as months, in order")
    series: list[AskSeries] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def series_match_points(self) -> "AskChart":
        if any(len(series.values) != len(self.points) for series in self.series):
            raise ValueError("every series needs exactly one value for each point")
        return self


AskBlock = AskText | AskTable | AskFigures | AskChart


class AskReply(BaseModel):
    """What the model must hand back: an ordered list of blocks from the fixed set
    above. It cannot return anything else, so it cannot invent a layout."""

    blocks: list[AskBlock] = Field(min_length=1)


class AskAnswer(BaseModel):
    """What the assistant produced for one question."""

    answer: str = Field(description="The whole answer as plain text")
    blocks: list[AskBlock] = Field(description="The same answer as the blocks it is shown in")
    sources: list[AskSource] = Field(description="The records the answer rests on")
    steps: list[AskStep] = Field(description="Each tool the assistant used, in order, with its inputs")
    worked_out: list[str] = Field(
        description="Dollar figures in the answer that no tool returned: sums or differences the assistant calculated"
    )
    as_of: date


# --- Items ---------------------------------------------------------------------
# An item is one thing a person fixes: an invoice, a bill, or a gap on a job. The
# checks that fire on it become its tags.

ItemKind = Literal[
    "invoice_unpaid", "invoice_not_sent", "bill_stuck", "bill_no_job", "cost_gap", "billing_gap",
    "late_start", "stalled", "budget_risk", "no_ops_manager", "flagged",
]
ActionKey = Literal["message_customer", "message_colleague", "code_bill", "assign_ops_manager", "wait", "dismiss"]


class ItemTag(BaseModel):
    key: str
    label: str


class ItemAction(BaseModel):
    """Something the app can start: a drafted message, a bill coding, an assignment, a date or a dismissal."""

    key: ActionKey
    label: str = Field(description="What the button says, such as Chase the customer")


class Suggestion(BaseModel):
    action: ItemAction
    reason: str | None = Field(description="Why, in one sentence. None when it is the standing rule for this kind of item")
    follow_up_on: date | None = Field(description="With wait: the date to come back")
    by: Literal["rule", "assistant"]


class SourceNote(BaseModel):
    """A note someone wrote in one of Harborstone's own systems."""

    by: str
    on: date
    note: str


class ItemResponse(BaseModel):
    key: str = Field(description="Stable name: the kind and what it is about, such as bill_stuck:APX-40766")
    kind: ItemKind
    title: str
    document: str | None
    company: str | None = Field(description="The customer or vendor on the document, when there is one")
    job_number: str | None
    job_name: str | None
    amount: Money
    severity: Literal["high", "medium"]
    tags: list[ItemTag]
    due_on: date | None
    days_late: int | None
    owner: str
    owner_role: Literal["ops_manager", "account_executive", "finance", "assigned"]
    state: Literal["needs_action", "waiting", "done"]
    follow_up_on: date | None
    note_count: int
    details: list[str] = Field(description="What is wrong, one sentence for each check that fired")
    resolution_note: str | None
    checks: list[str] = Field(description="The issue types behind this item")
    issue_ids: list[int]
    action: ItemAction = Field(description="The work that fixes this kind of item")
    suggestion: Suggestion
    evidence: list[LineResponse]
    events: list[EventResponse]
    source_notes: list[SourceNote] = Field(
        default_factory=list, description="Notes on this invoice in accounting, written before it reached this app"
    )


class JobSuggestion(BaseModel):
    """The one thing to do first on a job."""

    item_key: str
    action: ItemAction
    reason: str | None
    by: Literal["rule", "assistant"]


class JobItems(BaseModel):
    job_number: str | None = Field(description="None for bills that are not on any job")
    job_name: str | None
    ops_manager: str | None
    flagged_amount: Money = Field(description="Unpaid or unsent on this job's flagged invoices and bills, each counted once")
    tags: list[ItemTag] = Field(description="Every distinct tag on the job's items")
    items: list[ItemResponse]
    suggestion: JobSuggestion | None
    reviewed_at: datetime | None = Field(description="When the assistant last reviewed these items. None if it has not, or they have changed since")


class ItemsResponse(BaseModel):
    groups: list[JobItems]
    item_count: int


class ItemFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: Literal["open", "needs_action", "waiting", "done"] = "open"
    owner: str | None = None
    type: str | None = Field(None, description="Only jobs with an item that this issue type fired on")


class ItemActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    action: Literal["update", "resolve", "dismiss", "reopen"] = Field(
        description="update saves any of a note, a new owner and a follow-up date; dismiss closes it as expected"
    )
    actor: str = Field(min_length=1, max_length=120)
    note: str | None = None
    assignee: str | None = Field(None, max_length=120)
    follow_up_on: date | None = None
    follow_up_in_working_days: int | None = Field(None, ge=1, le=30, description="Set the follow-up this many working days from today")
    clear_follow_up: bool = False


class ReviewedItem(BaseModel):
    item_key: str
    decision: Literal["act", "wait", "dismiss"]
    wait_until: str | None = Field(description="With wait: the date to come back, as YYYY-MM-DD")
    reason: str = Field(min_length=1, max_length=300)


class ReviewReply(BaseModel):
    """What the model must hand back after reviewing a job's items."""

    items: list[ReviewedItem]
    first_item_key: str | None = Field(description="The item to deal with first, if any needs action")
    why_first: str | None


# --- Checks people add ---------------------------------------------------------

CheckSubject = Literal["job", "customer_invoice", "vendor_bill", "customer", "vendor"]


class RuleCondition(BaseModel):
    """One test in a rule: a field compared with a value, or with another field."""

    field: str = Field(description="A field name from the list given for this kind of record")
    op: Literal[">", ">=", "<", "<=", "=", "!=", "contains", "does_not_contain"] = Field(
        description="contains and does_not_contain are for text only, and match a word or phrase anywhere in it"
    )
    value: float | str | bool | None = Field(description="What the field is compared with. Empty when comparing with other_field")
    other_field: str | None = Field(description="Another field to compare with, instead of a value")
    times: float | None = Field(description="With other_field only: compare with that field multiplied by this, such as 1.1 for 110%")


class Rule(BaseModel):
    """A check written over the fixed fields of one kind of record. Code runs it; it is never sent to a model to judge."""

    match: Literal["all", "any"] = Field(description="all: every condition must hold. any: one is enough")
    conditions: list[RuleCondition] = Field(min_length=1, max_length=6)
    amount_field: str | None = Field(description="The money field that says how much is at stake, if one does")


class CheckDraftReply(BaseModel):
    """What the model hands back when asked to turn a person's words into a check."""

    title: str = Field(min_length=3, max_length=80, description="A short name for the check, in sentence case")
    subject: CheckSubject = Field(description="What it looks at: each job, customer invoice, vendor bill, customer or vendor")
    about: Literal["cash", "billing", "cost", "schedule", "ownership"]
    severity: Literal["high", "medium"] = Field(description="high when money is at risk now or a deadline is close; otherwise medium")
    approach: Literal["rule", "reading", "cannot"] = Field(
        description="rule: it can be tested on the fields. reading: only reading notes can tell. cannot: neither"
    )
    rule: Rule | None = Field(description="With approach rule only")
    reason: str = Field(min_length=1, max_length=300, description="One sentence: why this approach, or why it cannot be done")


class ReadingFlag(BaseModel):
    subject: str = Field(description="The job number or invoice number the notes belong to")
    quote: str = Field(min_length=1, max_length=300, description="The exact words in the notes that show the check applies")
    reason: str = Field(min_length=1, max_length=200, description="One sentence on why those words match the check")


class ReadingReply(BaseModel):
    """What the model hands back after reading subjects' notes for one check."""

    flagged: list[ReadingFlag]


class CheckDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    words: str = Field(min_length=8, max_length=600, description="What to look for, in the person's own words")


class CheckFinding(BaseModel):
    """One thing a check would flag, shown before it is saved."""

    subject: str
    job_number: str | None
    job_name: str | None
    amount: Money
    why: str


class CheckDraftResponse(BaseModel):
    title: str
    subject: CheckSubject
    about: str
    severity: str
    approach: Literal["rule", "reading", "cannot"]
    reason: str
    rule: Rule | None
    reads_as: str | None = Field(description="The rule in plain words, or what the assistant will read for")
    would_flag: list[CheckFinding]


class CheckCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=3, max_length=120)
    words: str = Field(min_length=8, max_length=600)
    subject: CheckSubject
    approach: Literal["rule", "reading"]
    rule: Rule | None = None
    severity: Literal["high", "medium"] = "medium"
    about: Literal["cash", "billing", "cost", "schedule", "ownership"]
    actor: str = Field(min_length=1, max_length=120)


# --- Commitments read from notes ------------------------------------------------

CommitmentKind = Literal["payment_promised", "promised_to_customer", "waiting_on", "we_will"]
CommitmentState = Literal["missed", "due_soon", "open", "kept", "done"]


class FoundCommitment(BaseModel):
    """One promise or wait the model found in one note."""

    note_id: int = Field(description="The note it was found in")
    kind: CommitmentKind = Field(
        description="payment_promised: a customer said they will pay. promised_to_customer: we promised the customer "
        "something. waiting_on: work is held up by someone outside the team. we_will: a next step the team said it would take"
    )
    who: str = Field(min_length=1, max_length=120, description="Who made the promise, or who is being waited on")
    what: str = Field(min_length=1, max_length=200, description="What was promised or is awaited, in a few plain words")
    due_on: str | None = Field(description="When it is due, as YYYY-MM-DD, only if the note gives or implies a date")


class CommitmentsReply(BaseModel):
    """What the model must hand back after reading a batch of notes."""

    commitments: list[FoundCommitment]


class CommitmentFilters(Paging):
    job: str | None = Field(None, description="Only this job, by job number")
    owner: str | None = Field(None, description="Only jobs this person is the ops manager of")
    kind: CommitmentKind | None = None
    state: Literal["active", "missed", "due_soon", "open", "kept", "done", "all"] = Field(
        "active", description="active: missed, due soon or open. Kept and done are finished"
    )


class CommitmentResponse(BaseModel):
    """A promise or a wait found in a note, and where it stands."""

    id: int
    kind: CommitmentKind
    who: str
    what: str
    due_on: date | None
    state: CommitmentState = Field(
        description="missed: its date has passed and it has not happened. due_soon: due within a week. "
        "kept: a payment promise the payments show was kept. done: a person marked it done"
    )
    job_number: str | None
    job_name: str | None
    document: str | None
    noted_by: str
    noted_on: date
    noted_in: Literal["project", "accounting"]
    note: str


class CommitmentAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["done", "reopen"]
    actor: str = Field(min_length=1, max_length=120)


class NoteReadingStatus(BaseModel):
    unread: int = Field(description="Notes the assistant has not read yet, or whose text changed since it did")
    read: int


class NotesReadResponse(BaseModel):
    notes_read: int
    commitments_found: int


# --- Bill coding ---------------------------------------------------------------


class CodingReply(BaseModel):
    """What the model must hand back about one bill."""

    decision: Literal["job", "not_a_job_cost", "unsure"]
    job_number: str | None = Field(description="The job, when the decision is job. Otherwise empty")
    confidence: Literal["high", "medium", "low"]
    reasons: list[str] = Field(min_length=1, max_length=4, description="The evidence, one short sentence each")
    runner_up_job_number: str | None = Field(description="Another job that came close, if any")


class CodingRunnerUp(BaseModel):
    job_number: str
    job_name: str


class CodingResponse(BaseModel):
    """A suggestion for a person to accept or reject. Nothing is changed by it."""

    bill: str
    decision: Literal["job", "not_a_job_cost", "unsure"]
    job_number: str | None
    job_name: str | None
    confidence: Literal["high", "medium", "low"]
    reasons: list[str]
    runner_up: CodingRunnerUp | None
    looked_at: list["AskStep"] = Field(description="Each lookup the agent used, in order")


# --- Follow-up drafts ------------------------------------------------------------


class DraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    writer: str = Field(min_length=1, max_length=120, description="Who will send the message. It is signed with their name")


class Copied(BaseModel):
    name: str
    role: str = Field(description="Why they are copied")
    email: str | None


class Recipient(BaseModel):
    """Who a follow-up goes to. Chosen from the records by fixed rules, never by the model."""

    audience: Literal["customer", "internal"]
    name: str
    role: str = Field(description="Why they are the person to write to")
    email: str | None = Field(description="None when the records hold no address for them")
    cc: list[Copied] = Field(default_factory=list, description="People copied in, such as the person named on the invoice")


class DraftReply(BaseModel):
    """What the model must hand back: the two parts of a message and nothing else."""

    subject: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=2400)


class DraftResponse(BaseModel):
    """A message for a person to read, change and send themselves. The app sends nothing."""

    recipient: Recipient
    subject: str
    body: str
    warnings: list[str] = Field(description="Things to check before sending, such as a figure that is not in the records")
    as_of: date


class AskResponse(BaseModel):
    """A saved exchange: the question, its answer, and when it was asked."""

    answer: str = Field(description="The whole answer as plain text")
    spec: dict = Field(
        description="The answer laid out for display: a json-render spec whose elements are Answer, Text, Table, Figures and Chart"
    )
    sources: list[AskSource]
    steps: list[AskStep]
    worked_out: list[str]
    as_of: date
    id: int
    question: str
    asked_by: str
    created_at: datetime


CodingResponse.model_rebuild()
JobDetailResponse.model_rebuild()
