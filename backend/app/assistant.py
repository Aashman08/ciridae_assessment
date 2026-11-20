"""Ask: answering questions about the reconciled data.

The model never touches the database and never writes a query. It can only
choose one of the tools below and fill in that tool's inputs. Each tool is a
fixed, read-only operation on `ReconClient`, so every figure in an answer comes
from the same code the rest of the app uses.

A person who only sees their own jobs gets the same limit here: the scope is
applied in our code, whatever inputs the model sends.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from agents import (
    Agent,
    ModelBehaviorError,
    RunContextWrapper,
    Runner,
    function_tool,
    set_default_openai_key,
    set_tracing_disabled,
)
from agents.models.interface import Model

from app import database
from app.errors import APIError, AskFailedError, IssueNotFoundError, JobNotFoundError
from app.financials import CostBasis, RevenueBasis
from app.schemas import (
    AskAnswer,
    AskBlock,
    AskMessage,
    AskPage,
    AskReply,
    AskRequest,
    AskSource,
    AskStep,
    IssueFilters,
    JobFilters,
    LineFilters,
)

logger = logging.getLogger(__name__)

# Conversations and figures stay with us; nothing is uploaded as a trace.
set_tracing_disabled(True)

MAX_TURNS = 8

NUMBER = re.compile(r"-?\d+(\.\d+)?")
# A dollar amount as written in an answer: $246,300 or $1,477,564.50
DOLLARS = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")
# A dollar sign followed by something that is not a whole figure: "$113,?" or "$?" or "$X".
BROKEN_FIGURE = re.compile(r"\$\s?(?:[\d,.]*\?|[A-Za-z])")

Stage = Literal["WORK_NOT_STARTED", "IN_PROGRESS", "COMPLETED", "CLOSED", "CANCELLED"]
IssueTypeKey = Literal[
    "closed_bills", "past_due", "not_sent", "over_contract", "closed_month", "cost_disagree",
    "no_ledger_cost", "rev_invoiced", "underbilled", "bill_overdue", "discount", "no_job", "no_owner",
]

INSTRUCTIONS = """\
You answer questions about Harborstone's jobs for its finance and operations staff.
Harborstone is a commercial restoration contractor. Its CRM, project system and
accounting system disagree about the same jobs, and this app reconciles them.

How to work:
- Every figure you state must come from a tool result in this conversation. Never
  estimate, recall or invent a number, a job, an invoice or a name.
- You may add, subtract or compare figures the tools returned. Say when you have.
- Write every figure in full. Never write a partial, rounded-off or placeholder
  figure. If you do not have a figure, leave the sentence out.
- To answer about a job named in words, find it with list_jobs, then use get_job
  with its job number for the exact figures.
- If the tools cannot answer the question, say so plainly and say what you can answer.
- All figures are as of {as_of}, the date of the last sync. "Past due" and "late" are
  measured against that date, not today.
- Each job has three cost figures (ops log, ledger, ledger plus unpaid bills) and three
  revenue figures (ledger, invoiced, collected). They differ on purpose. When you give
  a cost, revenue, profit or margin, say which figure it is.
- An "issue" is a place where the systems disagree, found by a fixed check.
{scope}
{page}

How to write:
- Your answer is a list of blocks. There are four kinds and no others:
  text: a sentence or two.
  table: several records with the same facts about each. One record per row and one
    fact per column. A job's number and its name are two columns, never one.
  figures: two to four headline figures, each with a short label.
  chart: a line or bar chart, drawn for you from the numbers you give. One to three
    series over the same ordered points. Use a line for change over time and bars to
    compare a few separate things. Give plain numbers as values, not text.
- When asked for a chart, graph, plot or trend, answer with a chart block. You can
  draw one; never say you cannot, and never imitate a chart with characters in a table.
- All series in one chart share one unit. Put dollars and counts in separate charts.
- Lead with a text block that gives the answer. Use a table whenever you list three or
  more jobs, invoices, bills, issues or customers; do not write them out as sentences.
- Do not repeat in text what a table already shows.
- Give each table column its kind: money for dollar amounts, number for counts, days
  and percentages, date for dates, text for everything else.
- No markdown anywhere: no asterisks, pound signs or pipes.
- Whole dollars with a dollar sign and commas, such as $246,300.
- Name jobs by job number and name, and invoices and bills by their number, so the
  reader can open them.
- Short sentences. No preamble and no closing offer of more help.
"""


@dataclass
class AskContext:
    """What the tools share during one question."""

    client: Any  # ReconClient; typed loosely to avoid importing it in a cycle
    owner: str | None
    steps: list[AskStep] = field(default_factory=list)
    # Everything the tools returned that the answer could point to, by its number.
    seen: dict[str, AskSource] = field(default_factory=dict)
    # Records the model looked up one at a time. These are always cited.
    opened: dict[str, AskSource] = field(default_factory=dict)
    # Every number any tool returned, in whole dollars, to check the answer against.
    figures: set[int] = field(default_factory=set)

    def result(self, value: Any) -> str:
        """What a tool hands back to the model: proper JSON, so nulls, booleans and
        quotes read as they would to any API caller. The numbers in it are noted,
        so the answer's figures can be checked against what was actually looked up."""
        self._note(value)
        return json.dumps(value, ensure_ascii=False)

    def _note(self, value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                self._note(item)
        elif isinstance(value, list):
            for item in value:
                self._note(item)
        elif isinstance(value, bool) or value is None:
            return
        elif isinstance(value, (int, float)) or (isinstance(value, str) and NUMBER.fullmatch(value)):
            try:
                self.figures.add(int(Decimal(str(value)).to_integral_value()))
            except InvalidOperation:
                pass

    def log(self, tool: str, **arguments: Any) -> None:
        self.steps.append(AskStep(tool=tool, arguments={k: v for k, v in arguments.items() if v is not None}))

    def saw_job(self, job_number: str, name: str, opened: bool = False) -> None:
        source = AskSource(kind="job", id=job_number, label=f"{job_number} {name}")
        (self.opened if opened else self.seen)[job_number] = source

    def saw_document(self, kind: Literal["invoice", "vendor_bill"], number: str | None, job_number: str | None) -> None:
        if number:
            self.seen[number] = AskSource(kind=kind, id=job_number or "", label=number)


Ctx = RunContextWrapper[AskContext]


def tool_error(ctx: RunContextWrapper[Any], error: Exception) -> str:
    """What the model is told when a tool call does not work, so it can correct
    itself or explain. Our own errors and bad inputs are passed on in plain words;
    anything unexpected is logged and kept vague."""
    if isinstance(error, APIError):
        return error.message
    if isinstance(error, ModelBehaviorError):
        # The SDK withholds which value was wrong, so remind the model what the tool accepts.
        name = getattr(ctx, "tool_name", "")
        accepted = next((t.params_json_schema.get("properties", {}) for t in TOOLS if t.name == name), {})
        return f"Those inputs are not valid for {name}. It accepts: {json.dumps(accepted)}"
    logger.error("Ask tool failed", exc_info=error)
    return "This tool failed. Do not guess the answer; say that this could not be looked up."


fixed_tool = function_tool(failure_error_function=tool_error)


def _limit(value: int, most: int = 25) -> int:
    return max(1, min(value, most))


def _dump(model: Any, *fields: str) -> dict:
    """Only the named fields of a response model, as plain JSON values."""
    return model.model_dump(mode="json", include=set(fields))


JOB_FIELDS = (
    "job_number", "name", "customer", "stage", "branch", "ops_manager", "account_executive", "contract_value",
    "budget", "planned_margin_pct", "ledger_profit", "ledger_margin_pct", "ledger_revenue", "invoiced", "collected", "owed", "past_due", "ops_cost",
    "ledger_cost", "unpaid_bills", "issue_count",
)
ISSUE_FIELDS = (
    "id", "title", "severity", "job_number", "job_name", "document", "due_on", "amount", "summary", "owner",
    "status", "note_count", "follow_up_on", "days_late",
)
LINE_FIELDS = ("doc_number", "company", "job_number", "amount", "paid_amount", "open_amount", "line_date", "due_date", "status")


@fixed_tool
async def company_summary(ctx: Ctx) -> str:
    """Totals across all jobs in scope: what customers owe, how much of that is past due,
    invoices not yet sent, vendor bills unpaid, contract-to-cash totals, and the number
    and dollar amount of open issues for each issue type. Start here for a general question."""
    ctx.context.log("company_summary")
    summary = await ctx.context.client.get_summary(ctx.context.owner)
    return ctx.context.result(summary.model_dump(mode="json", exclude={"sync_run_id", "owner"}))


@fixed_tool
async def list_jobs(
    ctx: Ctx,
    stage: Stage | None = None,
    branch: str | None = None,
    has_issues: bool | None = None,
    limit: int = 10,
) -> str:
    """Jobs with the figures each system holds, most open issues first.

    Args:
        stage: Only jobs at this stage.
        branch: Only jobs run from this branch, such as Dallas or Houston.
        has_issues: True for jobs with open issues, False for jobs with none.
        limit: How many jobs to return, 25 at most.
    """
    ctx.context.log("list_jobs", stage=stage, branch=branch, has_issues=has_issues, limit=limit)
    page = await ctx.context.client.list_jobs(
        JobFilters(stage=stage, branch=branch, has_issues=has_issues, owner=ctx.context.owner, limit=_limit(limit))
    )
    for job in page.data:
        ctx.context.saw_job(job.job_number, job.name)
    return ctx.context.result({"total": page.total, "jobs": [_dump(job, *JOB_FIELDS) for job in page.data]})


@fixed_tool
async def get_job(
    ctx: Ctx,
    job_number: str,
    revenue_basis: RevenueBasis = RevenueBasis.ledger,
    cost_basis: CostBasis = CostBasis.ledger,
) -> str:
    """Everything about one job: its figures from each system, the three revenue and three
    cost figures side by side, profit and margin for the chosen pair, its open issues,
    its customer invoices and its vendor bills.

    Args:
        job_number: The job's number, such as CTX00080002.
        revenue_basis: Which revenue figure to use for profit.
        cost_basis: Which cost figure to use for profit.
    """
    ctx.context.log("get_job", job_number=job_number, revenue_basis=revenue_basis, cost_basis=cost_basis)
    job = await ctx.context.client.get_job(job_number, revenue_basis, cost_basis)
    if ctx.context.owner and (job.ops_manager or "").lower() != ctx.context.owner.lower():
        # Outside this person's jobs. Answer exactly as if it did not exist.
        raise JobNotFoundError(job_number)
    ctx.context.saw_job(job.job_number, job.name, opened=True)
    for line in job.invoices:
        ctx.context.saw_document("invoice", line.doc_number, job.job_number)
    for line in job.vendor_bills:
        ctx.context.saw_document("vendor_bill", line.doc_number, job.job_number)
    return ctx.context.result({
        **_dump(job, *JOB_FIELDS, "won_on", "on_site_on", "planned_finish_on", "completed_on", "closed_on", "estimated_value"),
        "revenue_options": [_dump(o, "basis", "label", "amount") for o in job.revenue_options],
        "cost_options": [_dump(o, "basis", "label", "amount") for o in job.cost_options],
        "profit": job.profit.model_dump(mode="json"),
        "issues": [_dump(i, *ISSUE_FIELDS) for i in job.issues],
        "invoices": [_dump(l, *LINE_FIELDS) for l in job.invoices],
        "vendor_bills": [_dump(l, *LINE_FIELDS) for l in job.vendor_bills],
    })


@fixed_tool
async def list_issues(
    ctx: Ctx,
    issue_type: IssueTypeKey | None = None,
    severity: Literal["high", "medium"] | None = None,
    job_number: str | None = None,
    status: Literal["active", "resolved"] = "active",
    limit: int = 15,
) -> str:
    """Places where the systems disagree, largest dollar amount first.

    Args:
        issue_type: Only this kind of issue. Use list_issue_types to see what each means.
        severity: Only issues of this severity.
        job_number: Only issues on this job.
        status: "active" for open issues, "resolved" for ones people have closed.
        limit: How many issues to return, 25 at most.
    """
    ctx.context.log("list_issues", issue_type=issue_type, severity=severity, job_number=job_number, status=status, limit=limit)
    page = await ctx.context.client.list_issues(
        IssueFilters(
            type=issue_type, severity=severity, job=job_number, status=status,
            owner=ctx.context.owner, limit=_limit(limit),
        )
    )
    for issue in page.data:
        if issue.job_number:
            ctx.context.saw_job(issue.job_number, issue.job_name or "")
        if issue.document:
            ctx.context.seen[issue.document] = AskSource(kind="issue", id=str(issue.id), label=f"{issue.title}, {issue.document}")
    return ctx.context.result({"total": page.total, "issues": [_dump(issue, *ISSUE_FIELDS) for issue in page.data]})


@fixed_tool
async def list_issue_types(ctx: Ctx) -> str:
    """The thirteen checks: what each one looks for, its severity, its tolerance if it has
    one, and how many open issues and dollars it has found. Use this to explain an issue type."""
    ctx.context.log("list_issue_types")
    types = await ctx.context.client.list_issue_types()
    return ctx.context.result([t.model_dump(mode="json") for t in types])


@fixed_tool
async def list_invoices(ctx: Ctx, limit: int = 20) -> str:
    """Customer invoices across jobs, largest unpaid amount first, with status and due date.

    Args:
        limit: How many invoices to return, 25 at most.
    """
    ctx.context.log("list_invoices", limit=limit)
    page = await ctx.context.client.list_lines(
        LineFilters(kind="customer_invoice", owner=ctx.context.owner, limit=_limit(limit))
    )
    for line in page.data:
        ctx.context.saw_document("invoice", line.doc_number, line.job_number)
    return ctx.context.result({"total": page.total, "invoices": [_dump(line, *LINE_FIELDS) for line in page.data]})


@fixed_tool
async def list_vendor_bills(ctx: Ctx, no_job: bool | None = None, limit: int = 20) -> str:
    """Vendor bills across jobs, largest unpaid amount first, with status and due date.

    Args:
        no_job: True for only the bills that are not assigned to any job.
        limit: How many bills to return, 25 at most.
    """
    ctx.context.log("list_vendor_bills", no_job=no_job, limit=limit)
    page = await ctx.context.client.list_lines(
        LineFilters(kind="vendor_bill", owner=ctx.context.owner, no_job=no_job, limit=_limit(limit))
    )
    for line in page.data:
        ctx.context.saw_document("vendor_bill", line.doc_number, line.job_number)
    return ctx.context.result({"total": page.total, "vendor_bills": [_dump(line, *LINE_FIELDS) for line in page.data]})


@fixed_tool
async def owed_by_customer(ctx: Ctx, limit: int = 10) -> str:
    """What each customer owes in total and how much of it is past due, largest first.

    Args:
        limit: How many customers to return, 25 at most.
    """
    ctx.context.log("owed_by_customer", limit=limit)
    balances = await ctx.context.client.list_customer_balances(ctx.context.owner, _limit(limit))
    return ctx.context.result([b.model_dump(mode="json") for b in balances])


@fixed_tool
async def totals_by_month(ctx: Ctx, kind: Literal["customer_invoices", "vendor_bills"] = "customer_invoices") -> str:
    """Customer invoices or vendor bills totalled by the calendar month they are dated,
    oldest first: how many, the amount, how much is paid and unpaid, and for invoices how
    much has been sent. Use this for anything over time, a trend, or a chart by month.

    Args:
        kind: Which documents to total.
    """
    ctx.context.log("totals_by_month", kind=kind)
    months = await ctx.context.client.list_month_totals(
        "customer_invoice" if kind == "customer_invoices" else "vendor_bill", ctx.context.owner
    )
    return ctx.context.result([m.model_dump(mode="json") for m in months])


@fixed_tool
async def get_issue(ctx: Ctx, issue_id: int) -> str:
    """Everything about one issue: what is wrong, the suggested next step, who has it and
    why, the records behind it, the notes people have left, and any other open issues
    about the same invoice or bill.

    Args:
        issue_id: The issue's number, as given by list_issues or by the page the person is on.
    """
    ctx.context.log("get_issue", issue_id=issue_id)
    issue = await ctx.context.client.get_issue(issue_id)
    if ctx.context.owner and issue.owner.lower() != ctx.context.owner.lower():
        # Someone else's. Answer exactly as if it did not exist.
        raise IssueNotFoundError(issue_id)
    if issue.job_number:
        ctx.context.saw_job(issue.job_number, issue.job_name or "")
    label = f"{issue.title}, {issue.document}" if issue.document else issue.title
    ctx.context.opened[f"issue-{issue.id}"] = AskSource(kind="issue", id=str(issue.id), label=label)
    return ctx.context.result({
        **_dump(issue, *ISSUE_FIELDS, "detail", "next_step", "owner_role", "first_seen_on"),
        "records": [_dump(line, *LINE_FIELDS, "kind") for line in issue.evidence],
        "history": [_dump(event, "kind", "actor", "note", "created_at") for event in issue.events],
        "same_document": [_dump(other, "id", "title", "amount") for other in issue.related],
    })


TOOLS = [
    company_summary, list_jobs, get_job, list_issues, get_issue, list_issue_types,
    list_invoices, list_vendor_bills, owed_by_customer, totals_by_month,
]

PAGES = {
    "overview": "the overview of cash and issues",
    "jobs": "the list of jobs",
    "issues": "the list of issues",
    "invoices": "the list of customer invoices",
    "bills": "the list of vendor bills",
    "issue_types": "the list of issue types and their settings",
}


def on_screen(page: AskPage | None) -> str:
    """One instruction saying what the person is looking at. It names records for the
    tools to fetch; it carries no figures, so the answer still comes from the tools."""
    if page is None:
        return "- The person is asking from the Ask page, with nothing else on screen."
    if page.kind == "job" and page.job_number:
        return (
            f"- The person has job {page.job_number.upper()} open. \"This job\" or \"it\" means that job. "
            "Look it up with get_job before answering about it."
        )
    if page.kind == "issue" and page.issue_id:
        return (
            f"- The person has issue {page.issue_id} open. \"This issue\" or \"it\" means that issue. "
            "Look it up with get_issue before answering about it."
        )
    filters = ", ".join(f"{key} = {value}" for key, value in sorted(page.filters.items()))
    showing = f", filtered to {filters}" if filters else ""
    return f"- The person is looking at {PAGES.get(page.kind, 'the app')}{showing}. \"These\" or \"this list\" means what is on that page."


def is_configured() -> bool:
    return bool(database.settings.openai_api_key)


def build_model() -> str | Model | None:
    """The model to run. None means the SDK's own default."""
    set_default_openai_key(database.settings.openai_api_key, use_for_tracing=False)
    return database.settings.ask_model or None


def _cited(context: AskContext, answer: str) -> list[AskSource]:
    """What the answer rests on: every record looked up directly, plus any listed
    record whose number appears in the answer."""
    cited = dict(context.opened)
    for number, source in context.seen.items():
        if number in answer:
            cited.setdefault(number, source)
    return list(cited.values())


def worked_out(context: AskContext, answer: str) -> list[str]:
    """Dollar figures in the answer that no tool returned.

    These are sums or differences the assistant worked out itself. They are not
    wrong for that, but the reader should know which figures were read straight
    from the data and which were calculated on top of it.
    """
    derived: list[str] = []
    for match in DOLLARS.finditer(answer):
        written = match.group(0).replace(" ", "")
        amount = int(Decimal(match.group(1).replace(",", "")).to_integral_value())
        if amount not in context.figures and amount != 0 and written not in derived:
            derived.append(written)
    return derived


def _written(value: float, unit: str) -> str:
    """A charted value in words, in the same form the figure checks read."""
    if unit == "money":
        return f"-${abs(value):,.0f}" if value < 0 else f"${value:,.0f}"
    return f"{value:g}%" if unit == "percent" else f"{value:,.10g}"


def plain_text(blocks: list[AskBlock]) -> str:
    """The whole answer as plain text. The figure checks read this, and it is what
    the model is shown of its own earlier answers."""
    parts: list[str] = []
    for block in blocks:
        if block.type == "text":
            parts.append(block.text.strip())
        elif block.type == "table":
            parts.append("\n".join(", ".join(row) for row in block.rows))
        elif block.type == "figures":
            parts.append("\n".join(f"{item.label}: {item.value}" for item in block.items))
        else:
            lines = [block.title]
            for index, point in enumerate(block.points):
                values = "; ".join(f"{s.label} {_written(s.values[index], block.unit)}" for s in block.series)
                lines.append(f"{point}: {values}")
            parts.append("\n".join(lines))
    return "\n\n".join(part for part in parts if part)


async def answer(client: Any, request: AskRequest, as_of: date, history: list[AskMessage]) -> AskAnswer:
    """Run one question through the agent and return its answer with what it used.
    `history` is the earlier part of this person's conversation, oldest first."""
    scope = (
        f"- You are answering for {request.owner}, who only sees their own jobs. "
        "Every tool is already limited to those jobs. Do not describe company-wide totals."
        if request.owner
        else "- You are answering for someone who sees every job."
    )
    agent = Agent[AskContext](
        name="Harborstone reconciliation assistant",
        instructions=INSTRUCTIONS.format(as_of=f"{as_of:%d %B %Y}", scope=scope, page=on_screen(request.page)),
        tools=TOOLS,
        model=build_model(),
        # The reply is checked against the fixed set of blocks before we see it.
        output_type=AskReply,
    )
    context = AskContext(client=client, owner=request.owner)
    conversation: list[Any] = [{"role": m.role, "content": m.content} for m in history]
    conversation.append({"role": "user", "content": request.question})

    result = await Runner.run(agent, conversation, context=context, max_turns=MAX_TURNS)
    blocks = result.final_output.blocks
    text = plain_text(blocks)

    if BROKEN_FIGURE.search(text):
        # A figure came out incomplete, such as "$113,?". Ask once more, keeping the
        # lookups already done, and refuse to pass on an answer that is still broken.
        retry = result.to_input_list() + [
            {"role": "user", "content": "That answer contained an incomplete dollar figure. Answer again with every figure written in full."}
        ]
        result = await Runner.run(agent, retry, context=context, max_turns=MAX_TURNS)
        blocks = result.final_output.blocks
        text = plain_text(blocks)
        if BROKEN_FIGURE.search(text):
            logger.warning("Ask: answer still contained an incomplete figure after one retry")
            raise AskFailedError()

    # What the question cost, so spend can be read from the log and not guessed at.
    usage = result.context_wrapper.usage
    logger.info(
        "Ask used model=%s requests=%s input_tokens=%s output_tokens=%s lookups=%s",
        database.settings.ask_model or "default", usage.requests, usage.input_tokens, usage.output_tokens, len(context.steps),
    )

    return AskAnswer(
        answer=text,
        blocks=blocks,
        sources=_cited(context, text),
        steps=context.steps,
        worked_out=worked_out(context, text),
        as_of=as_of,
    )
