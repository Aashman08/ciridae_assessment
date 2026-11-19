"""Request validation and public response contracts. Money serializes as strings."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

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
    amount: Money
    summary: str
    detail: str
    next_step: str
    action_label: str
    owner: str
    status: str
    resolution_note: str | None
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
