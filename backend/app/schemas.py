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


class LineFilters(Paging):
    kind: str = Field(description="customer_invoice, vendor_bill, or any other money line kind")
    owner: str | None = Field(None, description="Limit to one ops manager's jobs")
    no_job: bool | None = Field(None, description="Only lines with no job assigned")


class IssueFilters(Paging):
    type: str | None = Field(None, description="Issue type key, such as past_due")
    owner: str | None = None
    status: str = Field("active", description="active (open or assigned), open, assigned, resolved, cleared or all")
    severity: Literal["high", "medium"] | None = None
    job: str | None = Field(None, description="Job number")


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
    status: str
    resolution_note: str | None
    note_count: int = Field(description="How many notes people have left on this issue")
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


class IssueDetailResponse(IssueResponse):
    evidence: list[LineResponse]
    events: list[EventResponse]


class IssueAction(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    action: Literal["assign", "comment", "resolve", "reopen"]
    actor: str = Field(min_length=1, max_length=120, description="Who is doing this")
    note: str | None = None
    assignee: str | None = Field(None, max_length=120)


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


class IssueTypeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    tolerance: Decimal | None = Field(None, ge=0)


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


# --- Summary -------------------------------------------------------------------


class CashSummary(BaseModel):
    owed: Money
    past_due: Money
    invoices_not_sent: Money
    invoices_not_sent_count: int
    vendor_bills_unpaid: Money
    vendor_bills_count: int
    invoice_count: int


class ContractToCash(BaseModel):
    contract_value: Money
    earned: Money
    invoiced: Money
    sent: Money
    collected: Money


class IssuesByType(BaseModel):
    type_key: str
    title: str
    severity: str
    count: int
    amount: Money


class SummaryResponse(BaseModel):
    sync_run_id: int
    as_of: date
    owner: str | None
    job_count: int
    cash: CashSummary
    contract_to_cash: ContractToCash
    open_issue_count: int
    jobs_with_issues: int
    issues_by_type: list[IssuesByType]


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


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=1000)
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
