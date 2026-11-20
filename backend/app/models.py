"""Our own tables.

`raw` holds untouched copies of source rows. `recon` holds the joined,
job-centred model, the computed totals and the issues found. Every money
line points back to the raw row it came from.

Relationships never load on their own (`lazy="raise"`). Under async a silent
lazy load would fail at an awkward moment, so every query names what it needs.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, column_property, mapped_column, relationship

RAW = "raw"
RECON = "recon"

Money = Numeric(14, 2)


class Base(DeclarativeBase):
    pass


class SyncRun(Base):
    """One end-to-end sync: land, normalize, total, find issues."""

    __tablename__ = "sync_run"
    __table_args__ = {"schema": RECON}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="running")
    # Date-based checks (past due, discount deadlines) are measured against this.
    as_of: Mapped[date] = mapped_column(Date)
    stats: Mapped[dict] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)


class SourceRecord(Base):
    """One source row, exactly as the source system returned it."""

    __tablename__ = "source_record"
    __table_args__ = (
        UniqueConstraint("table_name", "source_pk", name="uq_source_record_table_pk"),
        {"schema": RAW},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    system: Mapped[str] = mapped_column(String(20))
    table_name: Mapped[str] = mapped_column(String(80))
    source_pk: Mapped[str] = mapped_column(String(120))
    payload: Mapped[dict] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(String(64))
    first_seen_run_id: Mapped[int] = mapped_column(ForeignKey(f"{RECON}.sync_run.id"))
    last_changed_run_id: Mapped[int] = mapped_column(ForeignKey(f"{RECON}.sync_run.id"))
    last_seen_run_id: Mapped[int] = mapped_column(ForeignKey(f"{RECON}.sync_run.id"), index=True)


class Company(Base):
    """A customer or vendor. One company can be both."""

    __tablename__ = "company"
    __table_args__ = {"schema": RECON}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    is_customer: Mapped[bool] = mapped_column(Boolean, default=False)
    is_vendor: Mapped[bool] = mapped_column(Boolean, default=False)
    vendor_ref: Mapped[str | None] = mapped_column(String(40))
    discount_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    discount_days: Mapped[int | None] = mapped_column(Integer)
    source_record_id: Mapped[int] = mapped_column(ForeignKey(f"{RAW}.source_record.id"))
    sync_run_id: Mapped[int] = mapped_column(ForeignKey(f"{RECON}.sync_run.id"))


class Job(Base):
    """One won job: the CRM opportunity joined to its project."""

    __tablename__ = "job"
    __table_args__ = {"schema": RECON}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_number: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    customer_id: Mapped[int | None] = mapped_column(ForeignKey(f"{RECON}.company.id"))
    service_line: Mapped[str | None] = mapped_column(String(40))
    branch: Mapped[str | None] = mapped_column(String(80))
    crm_status: Mapped[str | None] = mapped_column(String(40))
    stage: Mapped[str] = mapped_column(String(40), index=True)
    won_on: Mapped[date | None] = mapped_column(Date)
    estimated_value: Mapped[Decimal | None] = mapped_column(Money)
    contract_value: Mapped[Decimal] = mapped_column(Money, default=0)
    original_contract_value: Mapped[Decimal | None] = mapped_column(Money)
    planned_margin_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    budget: Mapped[Decimal] = mapped_column(Money, default=0)
    on_site_on: Mapped[date | None] = mapped_column(Date)
    planned_finish_on: Mapped[date | None] = mapped_column(Date)
    completed_on: Mapped[date | None] = mapped_column(Date)
    closed_on: Mapped[date | None] = mapped_column(Date)
    cancelled_on: Mapped[date | None] = mapped_column(Date)
    opportunity_record_id: Mapped[int] = mapped_column(ForeignKey(f"{RAW}.source_record.id"))
    project_record_id: Mapped[int] = mapped_column(ForeignKey(f"{RAW}.source_record.id"))
    sync_run_id: Mapped[int] = mapped_column(ForeignKey(f"{RECON}.sync_run.id"))

    customer: Mapped[Company | None] = relationship(lazy="raise")
    owners: Mapped[list["JobOwner"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="JobOwner.role", lazy="raise"
    )


class JobOwner(Base):
    """A person in a role on a job."""

    __tablename__ = "job_owner"
    __table_args__ = (
        UniqueConstraint("job_id", "role", name="uq_job_owner_job_role"),
        {"schema": RECON},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey(f"{RECON}.job.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(30))  # ops_manager | account_executive
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(200))

    job: Mapped[Job] = relationship(back_populates="owners", lazy="raise")


class CostCodeMap(Base):
    """One source spelling of a cost category, mapped to our single list."""

    __tablename__ = "cost_code_map"
    __table_args__ = (
        UniqueConstraint("source_system", "source_code", name="uq_cost_code_map_source"),
        {"schema": RECON},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_system: Mapped[str] = mapped_column(String(20))
    source_code: Mapped[str] = mapped_column(String(80))
    category: Mapped[str] = mapped_column(String(60))
    note: Mapped[str | None] = mapped_column(Text)


class MoneyLine(Base):
    """One dollar amount of one kind, traceable to the source row behind it."""

    __tablename__ = "money_line"
    __table_args__ = (
        UniqueConstraint("source_table", "source_pk", name="uq_money_line_source"),
        {"schema": RECON},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # ops_cost | ledger_cost | ledger_revenue | ledger_receivable | ledger_receipt
    # | vendor_bill | customer_invoice | customer_payment
    kind: Mapped[str] = mapped_column(String(30), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey(f"{RECON}.job.id", ondelete="CASCADE"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey(f"{RECON}.company.id"))
    doc_number: Mapped[str | None] = mapped_column(String(60), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(Money)
    paid_amount: Mapped[Decimal] = mapped_column(Money, default=0)
    line_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str | None] = mapped_column(String(40))
    cost_category: Mapped[str | None] = mapped_column(String(60))
    source_table: Mapped[str] = mapped_column(String(80))
    source_pk: Mapped[str] = mapped_column(String(120))
    source_record_id: Mapped[int] = mapped_column(ForeignKey(f"{RAW}.source_record.id"))
    sync_run_id: Mapped[int] = mapped_column(ForeignKey(f"{RECON}.sync_run.id"))

    job: Mapped[Job | None] = relationship(lazy="raise")
    company: Mapped[Company | None] = relationship(lazy="raise")


class JobFinancials(Base):
    """The computed totals for one job in one sync run."""

    __tablename__ = "job_financials"
    __table_args__ = (
        UniqueConstraint("job_id", "sync_run_id", name="uq_job_financials_job_run"),
        {"schema": RECON},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey(f"{RECON}.job.id", ondelete="CASCADE"), index=True)
    sync_run_id: Mapped[int] = mapped_column(ForeignKey(f"{RECON}.sync_run.id"), index=True)
    contract_value: Mapped[Decimal] = mapped_column(Money, default=0)
    budget: Mapped[Decimal] = mapped_column(Money, default=0)
    # Cost, three ways. Kept separate on purpose: nothing links an ops cost
    # entry to a vendor bill, so they cannot be netted against each other.
    ops_cost: Mapped[Decimal] = mapped_column(Money, default=0)
    ledger_cost: Mapped[Decimal] = mapped_column(Money, default=0)
    unpaid_bills: Mapped[Decimal] = mapped_column(Money, default=0)
    # Revenue, from contract to cash.
    ledger_revenue: Mapped[Decimal] = mapped_column(Money, default=0)
    invoiced: Mapped[Decimal] = mapped_column(Money, default=0)
    sent: Mapped[Decimal] = mapped_column(Money, default=0)
    collected: Mapped[Decimal] = mapped_column(Money, default=0)
    owed: Mapped[Decimal] = mapped_column(Money, default=0)
    past_due: Mapped[Decimal] = mapped_column(Money, default=0)


class IssueType(Base):
    """One way the three systems can disagree about a job."""

    __tablename__ = "issue_type"
    __table_args__ = {"schema": RECON}

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    severity: Mapped[str] = mapped_column(String(10))  # high | medium
    about: Mapped[str] = mapped_column(String(20))  # cost | billing | cash | ownership
    description: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    tolerance: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    tolerance_unit: Mapped[str | None] = mapped_column(String(10))  # ratio | usd
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Issue(Base):
    """One finding. Keeps its identity, owner and history across syncs."""

    __tablename__ = "issue"
    __table_args__ = {"schema": RECON}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Issue type plus the record it is about. Stable from one sync to the next.
    key: Mapped[str] = mapped_column(String(120), unique=True)
    type_key: Mapped[str] = mapped_column(ForeignKey(f"{RECON}.issue_type.key"), index=True)
    # Optional: a vendor bill with no job is itself an issue.
    job_id: Mapped[int | None] = mapped_column(ForeignKey(f"{RECON}.job.id", ondelete="CASCADE"), index=True)
    subject: Mapped[str] = mapped_column(String(60))
    # The invoice or bill this is about, when it is about one. Job-level issues have none.
    document: Mapped[str | None] = mapped_column(String(60))
    # The date something has to happen by, when there is one: an invoice's or
    # bill's due date, or the last day to pay and still get a discount.
    due_on: Mapped[date | None] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Money, default=0)
    summary: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str] = mapped_column(Text)
    next_step: Mapped[str] = mapped_column(String(200))
    action_label: Mapped[str] = mapped_column(String(40))
    owner: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)  # open | assigned | resolved | cleared
    resolution_note: Mapped[str | None] = mapped_column(Text)
    first_seen_run_id: Mapped[int] = mapped_column(ForeignKey(f"{RECON}.sync_run.id"))
    last_seen_run_id: Mapped[int] = mapped_column(ForeignKey(f"{RECON}.sync_run.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    type: Mapped[IssueType] = relationship(lazy="raise")
    job: Mapped[Job | None] = relationship(lazy="raise")
    events: Mapped[list["IssueEvent"]] = relationship(
        back_populates="issue", cascade="all, delete-orphan", order_by="IssueEvent.id", lazy="raise"
    )
    evidence: Mapped[list["IssueEvidence"]] = relationship(cascade="all, delete-orphan", lazy="raise")


class IssueEvidence(Base):
    """A money line that an issue cites as proof."""

    __tablename__ = "issue_evidence"
    __table_args__ = {"schema": RECON}

    issue_id: Mapped[int] = mapped_column(ForeignKey(f"{RECON}.issue.id", ondelete="CASCADE"), primary_key=True)
    money_line_id: Mapped[int] = mapped_column(
        ForeignKey(f"{RECON}.money_line.id", ondelete="CASCADE"), primary_key=True
    )

    line: Mapped[MoneyLine] = relationship(lazy="raise")


class IssueEvent(Base):
    """One thing that happened to an issue."""

    __tablename__ = "issue_event"
    __table_args__ = {"schema": RECON}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey(f"{RECON}.issue.id", ondelete="CASCADE"), index=True)
    # opened | assigned | commented | resolved | reopened | cleared
    kind: Mapped[str] = mapped_column(String(20))
    actor: Mapped[str] = mapped_column(String(120), default="system")
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    issue: Mapped[Issue] = relationship(back_populates="events", lazy="raise")



class AskExchange(Base):
    """One question someone asked and the answer they got, kept so a conversation
    is still there when they come back to it."""

    __tablename__ = "ask_exchange"
    __table_args__ = {"schema": RECON}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asked_by: Mapped[str] = mapped_column(String(120), index=True)
    # Set when the person only sees their own jobs. The answer was limited to them.
    owner: Mapped[str | None] = mapped_column(String(120))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    # The answer as the blocks it is shown in. Empty for answers saved before blocks existed.
    blocks: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    sources: Mapped[list] = mapped_column(JSONB, default=list)
    steps: Mapped[list] = mapped_column(JSONB, default=list)
    worked_out: Mapped[list] = mapped_column(JSONB, default=list)
    as_of: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# How many notes people have left on an issue. Counted by the database as part
# of every issue read, so a list can show it without loading the history.
Issue.note_count = column_property(
    select(func.count(IssueEvent.id))
    .where(IssueEvent.issue_id == Issue.id, IssueEvent.kind == "commented")
    .correlate_except(IssueEvent)
    .scalar_subquery()
)
