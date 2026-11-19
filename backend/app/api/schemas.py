"""Shapes the API returns. Money is sent as plain numbers in dollars."""

from datetime import date, datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class SyncRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: str
    as_of: date
    started_at: datetime
    finished_at: datetime | None
    stats: dict
    error: str | None


class SyncRunIn(BaseModel):
    as_of: date | None = Field(None, description="Date that past-due and deadline checks are measured against. Defaults to the export date")


class LineOut(BaseModel):
    id: int
    kind: str
    doc_number: str | None
    description: str | None
    job_number: str | None
    company: str | None
    amount: float
    paid_amount: float
    open_amount: float
    line_date: date | None
    due_date: date | None
    status: str | None
    cost_category: str | None
    source_table: str
    source_record_id: int


class TopIssue(BaseModel):
    type_key: str
    title: str
    amount: float


class JobSummary(BaseModel):
    job_number: str
    name: str
    customer: str | None
    stage: str
    branch: str | None
    service_line: str | None
    ops_manager: str | None
    account_executive: str | None
    contract_value: float
    budget: float
    planned_margin_pct: float | None
    ledger_revenue: float
    invoiced: float
    sent: float
    collected: float
    owed: float
    past_due: float
    ops_cost: float
    ledger_cost: float
    unpaid_bills: float
    issue_count: int
    top_issue: TopIssue | None


class FigureOption(BaseModel):
    basis: str
    label: str
    description: str
    amount: float


class ProfitOut(BaseModel):
    revenue_basis: str
    cost_basis: str
    revenue: float
    cost: float
    profit: float
    margin_pct: float | None
    planned_margin_pct: float | None


class IssueOut(BaseModel):
    id: int
    key: str
    type_key: str
    title: str
    severity: str
    about: str
    job_number: str | None
    job_name: str | None
    subject: str
    amount: float
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


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    actor: str
    note: str | None
    created_at: datetime


class IssueDetail(IssueOut):
    evidence: list[LineOut]
    events: list[EventOut]


class IssueActionIn(BaseModel):
    action: Literal["assign", "comment", "resolve", "reopen"]
    actor: str = Field(..., min_length=1, description="Who is doing this")
    note: str | None = None
    assignee: str | None = None


class JobDetail(JobSummary):
    estimated_value: float | None
    original_contract_value: float | None
    won_on: date | None
    on_site_on: date | None
    planned_finish_on: date | None
    completed_on: date | None
    closed_on: date | None
    cancelled_on: date | None
    crm_status: str | None
    revenue_options: list[FigureOption]
    cost_options: list[FigureOption]
    profit: ProfitOut
    issues: list[IssueOut]
    invoices: list[LineOut]
    vendor_bills: list[LineOut]


class IssueTypeOut(BaseModel):
    key: str
    title: str
    severity: str
    about: str
    description: str
    enabled: bool
    tolerance: float | None
    tolerance_unit: str | None
    open_count: int
    open_amount: float


class IssueTypePatch(BaseModel):
    enabled: bool | None = None
    tolerance: float | None = Field(None, ge=0)


class CashOut(BaseModel):
    owed: float
    past_due: float
    invoices_not_sent: float
    invoices_not_sent_count: int
    vendor_bills_unpaid: float
    vendor_bills_count: int


class ContractToCash(BaseModel):
    contract_value: float
    earned: float
    invoiced: float
    sent: float
    collected: float


class IssuesByType(BaseModel):
    type_key: str
    title: str
    severity: str
    count: int
    amount: float


class SummaryOut(BaseModel):
    sync_run_id: int
    as_of: date
    owner: str | None
    job_count: int
    cash: CashOut
    contract_to_cash: ContractToCash
    open_issue_count: int
    jobs_with_issues: int
    issues_by_type: list[IssuesByType]


class SourceRecordOut(BaseModel):
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
