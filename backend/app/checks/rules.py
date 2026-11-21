"""Checks people add, written as rules over fixed fields.

A rule names fields from a fixed list for one kind of record (a job, a customer
invoice, a vendor bill, a customer or a vendor), compares each with a value or with
another field, and says whether all or any of those tests must hold. Our code compiles
it to one SQL query and runs it on every sync, next to the built-in checks in
`issues.py`, and its findings become issues the same way theirs do. No model is
involved in running a rule; a model only helps write one, and what it writes is
checked here first.

The fields are the assistant's whole view of the data when it writes a rule, so they
cover everything the three systems hold: figures, dates, people, statuses, counts and
the words on invoice and bill lines.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Callable

from sqlalchemy import Date, Integer, Numeric, and_, cast, distinct, exists, func, literal, or_, select, type_coerce
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.errors import InvalidRequestError
from app.sync.financials import LEDGER_MARGIN, LEDGER_PROFIT
from app.checks.issues import (
    ACCOUNT_EXECUTIVE, FINANCE_QUEUE, OPS_MANAGER, OWNER, VENDOR_NAME, Finding, customer, fin, line, money, vendor,
)
from app.core.models import Company, Issue, IssueType, Job, MoneyLine, Note, SourceRecord, SyncRun
from app.core.schemas import Rule, RuleCondition

NUMBERS = ("money", "number", "days", "percent")
TEXT_OPS = ("=", "!=", "contains", "does_not_contain")


@dataclass(frozen=True)
class FactField:
    label: str
    kind: str  # money | number | days | percent | text | bool
    sql: Callable[[date], object]
    about: str


def _const(expression):
    return lambda as_of: expression


def _days_since(column):
    return lambda as_of: type_coerce(literal(as_of, Date) - column, Integer)


def _days_until(column):
    return lambda as_of: type_coerce(column - literal(as_of, Date), Integer)


def _pct(part, whole):
    return cast(part * 100 / func.nullif(whole, 0), Numeric(12, 1))


# --- Pieces of SQL about one job, used by several kinds of record ----------------

other = aliased(MoneyLine)
raw_line = aliased(SourceRecord)
email = aliased(SourceRecord)
attachment = aliased(SourceRecord)
customer_co = aliased(Company)
vendor_co = aliased(Company)


def _sum_lines(kind: str, value, *where, on=None):
    on = on if on is not None else other.job_id == Job.id
    return select(func.coalesce(func.sum(value), 0)).where(other.kind == kind, on, *where).correlate_except(other).scalar_subquery()


def _count_lines(kind: str, *where, on=None):
    on = on if on is not None else other.job_id == Job.id
    return select(func.count()).where(other.kind == kind, on, *where).correlate_except(other).scalar_subquery()


OPEN = other.amount - other.paid_amount
CUSTOMER_NAME = select(customer_co.name).where(customer_co.id == Job.customer_id).correlate(Job).scalar_subquery()
LAST_WORK = (
    select(func.max(other.line_date))
    .where(other.job_id == Job.id, other.kind.in_(("ops_cost", "vendor_bill")))
    .correlate_except(other)
    .scalar_subquery()
)


def _lines_text(table: str):
    """The descriptions on a document's lines, as the source system has them, joined into one text."""
    return (
        select(func.coalesce(func.string_agg(raw_line.payload["description"].astext, "; "), ""))
        .where(raw_line.table_name == table, raw_line.payload["invoice_id"].astext == line.source_pk)
        .correlate(line)
        .scalar_subquery()
    )


EMAIL_SUBJECT = (
    select(email.payload["subject"].astext)
    .where(
        email.table_name == "inbound_emails",
        or_(
            email.payload["subject"].astext.ilike(func.concat("%", line.doc_number, "%")),
            email.source_pk.in_(
                select(attachment.payload["inbound_email_id"].astext)
                .where(
                    attachment.table_name == "inbound_email_attachments",
                    attachment.payload["filename"].astext.ilike(func.concat(line.doc_number, ".%")),
                )
                .correlate(line)
            ),
        ),
    )
    .correlate(line)
    .limit(1)
    .scalar_subquery()
)

# --- The fields, by kind of record ---------------------------------------------

JOB_FIELDS: dict[str, FactField] = {
    "job_name": FactField("Job name", "text", _const(Job.name), "The site and job's name"),
    "customer": FactField("Customer", "text", _const(func.coalesce(CUSTOMER_NAME, "")), "The customer's name"),
    "stage": FactField("Stage", "text", _const(Job.stage), "Where the job is in the project system"),
    "crm_status": FactField("CRM status", "text", _const(func.coalesce(Job.crm_status, "")), "The opportunity's status in the CRM"),
    "kind_of_work": FactField("Kind of work", "text", _const(func.coalesce(Job.service_line, "")), "Mitigation, roofing, construction and so on"),
    "loss_type": FactField("Loss type", "text", _const(func.coalesce(Job.loss_type, "")), "What caused the damage, from the CRM"),
    "branch": FactField("Branch", "text", _const(func.coalesce(Job.branch, "")), "The branch running the job"),
    "ops_manager": FactField("Ops manager", "text", _const(func.coalesce(OPS_MANAGER, "")), "The ops manager's name, empty when there is none"),
    "account_executive": FactField("Account executive", "text", _const(func.coalesce(ACCOUNT_EXECUTIVE, "")), "Who sold the job"),
    "has_ops_manager": FactField("Has an ops manager", "bool", _const(OPS_MANAGER.is_not(None)), "An ops manager is named for the job"),
    "urgent": FactField("Urgent", "bool", _const(Job.urgent_reason.is_not(None)), "Emergency mitigation or a named catastrophe"),
    "contract_value": FactField("Contract value", "money", _const(Job.contract_value), "The contract value now"),
    "original_contract_value": FactField("Original contract value", "money", _const(func.coalesce(Job.original_contract_value, Job.contract_value)), "Before any change order"),
    "contract_change": FactField("Change in contract", "money", _const(Job.contract_value - func.coalesce(Job.original_contract_value, Job.contract_value)), "What change orders added (or took off)"),
    "estimated_value": FactField("Estimated value", "money", _const(func.coalesce(Job.estimated_value, 0)), "The value estimated in the CRM when won"),
    "budget": FactField("Budget", "money", _const(Job.budget), "The job's cost budget"),
    "ops_cost": FactField("Cost logged by the project team", "money", _const(fin.ops_cost), "Cost entered in the project system"),
    "ledger_cost": FactField("Cost in the ledger", "money", _const(fin.ledger_cost), "Job cost finance has booked"),
    "ledger_revenue": FactField("Revenue in the ledger", "money", _const(fin.ledger_revenue), "Revenue finance has booked"),
    "ledger_profit": FactField("Profit in the ledger", "money", _const(LEDGER_PROFIT), "Ledger revenue less ledger cost"),
    "ledger_margin_pct": FactField("Margin in the ledger", "percent", _const(cast(LEDGER_MARGIN * 100, Numeric(12, 1))), "Ledger profit as a share of ledger revenue"),
    "planned_margin_pct": FactField("Planned margin", "percent", _const(func.coalesce(Job.planned_margin_pct, 0)), "The margin the project was priced at"),
    "budget_used_pct": FactField("Share of budget used", "percent", _const(_pct(fin.ops_cost, Job.budget)), "Cost logged as a share of budget"),
    "time_used_pct": FactField(
        "Share of schedule gone", "percent",
        lambda as_of: _pct(literal(as_of, Date) - Job.on_site_on, Job.planned_finish_on - Job.on_site_on),
        "Days since on site as a share of the planned length",
    ),
    "invoiced": FactField("Invoiced", "money", _const(fin.invoiced), "Every invoice raised, sent or not"),
    "collected": FactField("Collected", "money", _const(fin.collected), "Cash received from the customer"),
    "owed": FactField("Owed by the customer", "money", _const(fin.owed), "Sent and not yet paid"),
    "past_due": FactField("Past due", "money", _const(fin.past_due), "Owed and past its due date"),
    "unpaid_bills": FactField("Unpaid vendor bills", "money", _const(fin.unpaid_bills), "Vendor bills on the job not yet paid"),
    "open_invoice_count": FactField("Open invoices", "number", _const(_count_lines("customer_invoice", OPEN > 0)), "Invoices with something still unpaid"),
    "unpaid_bill_count": FactField("Unpaid vendor bills (count)", "number", _const(_count_lines("vendor_bill", OPEN > 0)), "Vendor bills not fully paid"),
    "open_issue_count": FactField(
        "Open issues", "number",
        _const(select(func.count()).where(Issue.job_id == Job.id, Issue.status.in_(("open", "assigned"))).correlate(Job).scalar_subquery()),
        "Issues still open on the job",
    ),
    "note_count": FactField("Notes", "number", _const(select(func.count()).where(Note.job_id == Job.id).correlate(Job).scalar_subquery()), "Notes written on the job or its invoices"),
    "days_since_won": FactField("Days since won", "days", _days_since(Job.won_on), "Days from the win to the date of the figures"),
    "days_since_incident": FactField("Days since the damage", "days", _days_since(Job.incident_on), "Days since the loss happened"),
    "days_since_on_site": FactField("Days since on site", "days", _days_since(Job.on_site_on), "Days since the crew was first on site"),
    "days_to_planned_finish": FactField("Days to planned finish", "days", _days_until(Job.planned_finish_on), "Negative once the planned finish has passed"),
    "days_since_completed": FactField("Days since completed", "days", _days_since(Job.completed_on), "Empty until the work is complete"),
    "days_since_closed": FactField("Days since closed", "days", _days_since(Job.closed_on), "Empty until the job is closed"),
    "days_since_last_work": FactField("Days since last work", "days", lambda as_of: type_coerce(literal(as_of, Date) - LAST_WORK, Integer), "Days since the last cost or vendor bill was dated"),
}

ON_THIS_JOB = {
    "job_name": FactField("Job name", "text", _const(func.coalesce(Job.name, "")), "The job it is on"),
    "job_stage": FactField("Job stage", "text", _const(func.coalesce(Job.stage, "")), "The stage of the job it is on"),
    "kind_of_work": FactField("Kind of work", "text", _const(func.coalesce(Job.service_line, "")), "The job's kind of work"),
    "branch": FactField("Branch", "text", _const(func.coalesce(Job.branch, "")), "The job's branch"),
    "ops_manager": FactField("Ops manager", "text", _const(func.coalesce(OPS_MANAGER, "")), "The job's ops manager"),
}

DOCUMENT_FIELDS: dict[str, FactField] = {
    "number": FactField("Number", "text", _const(func.coalesce(line.doc_number, "")), "The document's number"),
    "amount": FactField("Amount", "money", _const(line.amount), "The document's total"),
    "paid": FactField("Paid", "money", _const(line.paid_amount), "Paid against it so far"),
    "open_amount": FactField("Open amount", "money", _const(line.amount - line.paid_amount), "Total less paid"),
    "status": FactField("Status", "text", _const(func.coalesce(line.status, "")), "Its status in accounting"),
    "days_since_dated": FactField("Days since dated", "days", _days_since(line.line_date), "Days since its date"),
    "days_past_due": FactField("Days past due", "days", _days_since(line.due_date), "Negative while it is not yet due"),
    "days_until_due": FactField("Days until due", "days", _days_until(line.due_date), "Negative once it is past due"),
    **ON_THIS_JOB,
}

INVOICE_FIELDS = {
    **DOCUMENT_FIELDS,
    "customer": FactField("Customer", "text", _const(func.coalesce(customer.name, "")), "The customer's name"),
    "lines_text": FactField("What it bills for", "text", _const(_lines_text("ar_invoice_lines")), "The descriptions on the invoice's lines"),
    "payment_count": FactField("Payments", "number", _const(_count_lines("customer_payment", on=other.doc_number == line.doc_number)), "Payments received against it"),
    "days_since_last_payment": FactField(
        "Days since last payment", "days",
        lambda as_of: type_coerce(
            literal(as_of, Date)
            - select(func.max(other.line_date)).where(other.kind == "customer_payment", other.doc_number == line.doc_number).correlate(line).scalar_subquery(),
            Integer,
        ),
        "Empty when nothing has been paid",
    ),
    "has_note": FactField("Has a note in accounting", "bool", _const(exists().where(Note.document == line.doc_number)), "Someone has written a note on it"),
}

BILL_FIELDS = {
    **DOCUMENT_FIELDS,
    "vendor": FactField("Vendor", "text", _const(VENDOR_NAME), "The vendor's name"),
    "is_on_a_job": FactField("Is on a job", "bool", _const(line.job_id.is_not(None)), "The bill is assigned to a job"),
    "cost_code": FactField("Cost code", "text", _const(func.coalesce(line.cost_category, "")), "Its cost code"),
    "lines_text": FactField("What it bills for", "text", _const(_lines_text("ap_invoice_lines")), "The descriptions on the bill's lines"),
    "email_subject": FactField("Email it came on", "text", _const(func.coalesce(EMAIL_SUBJECT, "")), "The subject of the email it arrived on, empty if none"),
    "came_by_email": FactField("Came by email", "bool", _const(EMAIL_SUBJECT.is_not(None)), "It arrived on an email to accounts payable"),
    "discount_pct": FactField("Early-pay discount", "percent", _const(func.coalesce(vendor.discount_pct, 0)), "The vendor's early-payment discount, 0 if none"),
    "discount_days_left": FactField(
        "Days left for the discount", "days",
        lambda as_of: type_coerce(line.line_date + func.coalesce(vendor.discount_days, 0) - literal(as_of, Date), Integer),
        "Days until the early-pay deadline; negative once it has passed",
    ),
}

CUSTOMER_FIELDS: dict[str, FactField] = {
    "name": FactField("Customer", "text", _const(Company.name), "The customer's name"),
    "owed": FactField("Owed", "money", _const(_sum_lines("customer_invoice", OPEN, other.status == "SENT", on=other.company_id == Company.id)), "Sent and not yet paid, across their invoices"),
    "past_due": FactField(
        "Past due", "money",
        lambda as_of: _sum_lines("customer_invoice", OPEN, other.status == "SENT", other.due_date < as_of, on=other.company_id == Company.id),
        "Owed and past its due date",
    ),
    "open_invoice_count": FactField("Open invoices", "number", _const(_count_lines("customer_invoice", OPEN > 0, on=other.company_id == Company.id)), "Invoices with something still unpaid"),
    "oldest_days_past_due": FactField(
        "Oldest days past due", "days",
        lambda as_of: select(func.coalesce(func.max(literal(as_of, Date) - other.due_date), 0))
        .where(other.kind == "customer_invoice", other.company_id == Company.id, other.status == "SENT", OPEN > 0)
        .correlate_except(other).scalar_subquery(),
        "How late their most overdue invoice is",
    ),
    "invoiced_total": FactField("Invoiced", "money", _const(_sum_lines("customer_invoice", other.amount, on=other.company_id == Company.id)), "Every invoice raised to them"),
    "collected_total": FactField("Collected", "money", _const(_sum_lines("customer_payment", other.amount, on=other.company_id == Company.id)), "Cash received from them"),
    "job_count": FactField("Jobs", "number", _const(select(func.count()).where(Job.customer_id == Company.id).correlate(Company).scalar_subquery()), "Jobs for this customer"),
    "active_job_count": FactField(
        "Active jobs", "number",
        _const(select(func.count()).where(Job.customer_id == Company.id, Job.stage.in_(("WON", "IN_PROGRESS"))).correlate(Company).scalar_subquery()),
        "Jobs won or in progress",
    ),
}

VENDOR_FIELDS: dict[str, FactField] = {
    "name": FactField("Vendor", "text", _const(Company.name), "The vendor's name"),
    "unpaid_total": FactField("Unpaid", "money", _const(_sum_lines("vendor_bill", OPEN, on=other.company_id == Company.id)), "Unpaid across their bills"),
    "bill_count": FactField("Bills", "number", _const(_count_lines("vendor_bill", on=other.company_id == Company.id)), "Bills from this vendor"),
    "unpaid_bill_count": FactField("Unpaid bills", "number", _const(_count_lines("vendor_bill", OPEN > 0, on=other.company_id == Company.id)), "Bills not fully paid"),
    "bills_on_no_job": FactField("Bills on no job", "number", _const(_count_lines("vendor_bill", other.job_id.is_(None), on=other.company_id == Company.id)), "Their bills not assigned to a job"),
    "oldest_days_past_due": FactField(
        "Oldest days past due", "days",
        lambda as_of: select(func.coalesce(func.max(literal(as_of, Date) - other.due_date), 0))
        .where(other.kind == "vendor_bill", other.company_id == Company.id, OPEN > 0)
        .correlate_except(other).scalar_subquery(),
        "How late their most overdue unpaid bill is",
    ),
    "job_count": FactField(
        "Jobs billed", "number",
        _const(select(func.count(distinct(other.job_id))).where(other.kind == "vendor_bill", other.company_id == Company.id).correlate_except(other).scalar_subquery()),
        "Jobs they have billed",
    ),
    "discount_pct": FactField("Early-pay discount", "percent", _const(func.coalesce(Company.discount_pct, 0)), "Their early-payment discount, 0 if none"),
    "has_discount_terms": FactField("Offers an early-pay discount", "bool", _const(Company.discount_pct.is_not(None)), "They have discount terms"),
}

FIELDS: dict[str, dict[str, FactField]] = {
    "job": JOB_FIELDS, "customer_invoice": INVOICE_FIELDS, "vendor_bill": BILL_FIELDS,
    "customer": CUSTOMER_FIELDS, "vendor": VENDOR_FIELDS,
}
SUBJECT_WORDS = {"job": "job", "customer_invoice": "customer invoice", "vendor_bill": "vendor bill", "customer": "customer", "vendor": "vendor"}
OPS_WORDS = {
    ">": "is more than", ">=": "is at least", "<": "is less than", "<=": "is at most", "=": "is", "!=": "is not",
    "contains": "mentions", "does_not_contain": "does not mention",
}


def catalogue(subject: str, values: dict[str, list[str]] | None = None) -> list[dict]:
    """The fields a rule may use for one kind of record, as the model is shown them, with
    the values each text field actually holds today so it writes ones that exist."""
    values = values or {}
    return [
        {"field": name, "label": f.label, "type": f.kind, "meaning": f.about, **({"values_today": values[name]} if name in values else {})}
        for name, f in FIELDS[subject].items()
    ]


def validate(rule: Rule, subject: str) -> Rule:
    """A rule may only name fields that exist for its kind of record, and compare like with like."""
    fields = FIELDS[subject]
    for c in rule.conditions:
        f = fields.get(c.field)
        if f is None:
            raise InvalidRequestError(f"'{c.field}' is not a field a {SUBJECT_WORDS[subject]} check can use.")
        if c.other_field is not None:
            other_field = fields.get(c.other_field)
            if other_field is None or f.kind not in NUMBERS or other_field.kind not in NUMBERS:
                raise InvalidRequestError(f"'{c.field}' cannot be compared with '{c.other_field}'.")
            if c.op in TEXT_OPS[2:]:
                raise InvalidRequestError(f"'{c.op}' only applies to text.")
            continue
        if c.value is None:
            raise InvalidRequestError(f"The test on '{c.field}' needs a value to compare with.")
        if f.kind in NUMBERS and (isinstance(c.value, bool) or not isinstance(c.value, (int, float)) or c.op in TEXT_OPS[2:]):
            raise InvalidRequestError(f"'{c.field}' is a number, so it must be compared with a number.")
        if f.kind == "text" and (not isinstance(c.value, str) or c.op not in TEXT_OPS):
            raise InvalidRequestError(f"'{c.field}' is text: it can be equal to, not equal to, or mention a word.")
        if f.kind == "bool" and (not isinstance(c.value, bool) or c.op not in ("=", "!=")):
            raise InvalidRequestError(f"'{c.field}' is yes or no: compare it with true or false.")
    if rule.amount_field is not None and (fields.get(rule.amount_field) is None or fields[rule.amount_field].kind != "money"):
        raise InvalidRequestError(f"'{rule.amount_field}' is not a money field.")
    return rule


def _value_words(f: FactField, value) -> str:
    if value is None:
        return "not recorded"
    if f.kind == "money":
        return money(Decimal(str(value)))
    if f.kind == "days":
        return f"{float(value):g} days"
    if f.kind == "percent":
        return f"{float(value):g}%"
    if f.kind == "bool":
        return "yes" if value else "no"
    if f.kind == "text":
        return str(value).replace("_", " ").lower() if str(value).isupper() else str(value)
    return f"{float(value):g}"


def in_words(rule: Rule, subject: str) -> str:
    """The rule as a sentence a person can check: "Flags a customer invoice where open amount is more than $100,000 and …"."""
    fields = FIELDS[subject]
    parts = []
    for c in rule.conditions:
        f = fields[c.field]
        if c.other_field:
            other_label = fields[c.other_field].label.lower()
            scaled = f"{c.times * 100:g}% of {other_label}" if c.times not in (None, 1) else other_label
            parts.append(f"{f.label.lower()} {OPS_WORDS[c.op]} {scaled}")
        elif f.kind == "text" and c.op in TEXT_OPS[2:]:
            parts.append(f"{f.label.lower()} {OPS_WORDS[c.op]} “{c.value}”")
        else:
            parts.append(f"{f.label.lower()} {OPS_WORDS[c.op]} {_value_words(f, c.value)}")
    joiner = " and " if rule.match == "all" else " or "
    article = "an" if SUBJECT_WORDS[subject][0] in "aeiou" else "a"
    return f"Flags {article} {SUBJECT_WORDS[subject]} where " + joiner.join(parts)


def _test(c: RuleCondition, fields: dict[str, FactField], as_of: date):
    f = fields[c.field]
    left = f.sql(as_of)
    if c.other_field:
        right = fields[c.other_field].sql(as_of)
        if c.times not in (None, 1):
            right = right * Decimal(str(c.times))
    elif f.kind == "text":
        word = str(c.value)
        if c.op == "contains":
            return left.ilike(f"%{word}%")
        if c.op == "does_not_contain":
            return ~left.ilike(f"%{word}%")
        left, right = func.upper(left), word.upper()
    else:
        right = c.value if isinstance(c.value, bool) else Decimal(str(c.value))
    # Built only for the comparison asked for: some, such as ">" on a yes/no field, are not valid SQL.
    return {
        ">": lambda: left > right, ">=": lambda: left >= right, "<": lambda: left < right,
        "<=": lambda: left <= right, "=": lambda: left == right, "!=": lambda: left != right,
    }[c.op]()


def base(subject: str, run: SyncRun):
    """One row per record of this kind, with who owns it and how to name it."""
    none = literal(None)
    if subject == "job":
        return select(
            Job.id.label("job_id"), Job.job_number, Job.name.label("job_name"), Job.job_number.label("subject"),
            OWNER, none.label("line_id"), none.label("document"),
        ).join(fin, and_(fin.job_id == Job.id, fin.sync_run_id == run.id)).where(Job.stage != "CANCELLED")
    if subject in ("customer", "vendor"):
        flag = Company.is_customer if subject == "customer" else Company.is_vendor
        return select(
            none.label("job_id"), none.label("job_number"), none.label("job_name"), Company.name.label("subject"),
            literal(FINANCE_QUEUE).label("owner"), none.label("line_id"), none.label("document"),
        ).where(flag)
    query = (
        select(
            Job.id.label("job_id"), Job.job_number, Job.name.label("job_name"), line.doc_number.label("subject"),
            OWNER, line.id.label("line_id"), line.doc_number.label("document"),
        )
        .outerjoin(Job, Job.id == line.job_id)
        .where(line.kind == subject)
    )
    if subject == "customer_invoice":
        return query.outerjoin(customer, customer.id == Job.customer_id)
    return query.outerjoin(vendor, vendor.id == line.company_id)


async def values_today(db: AsyncSession, run: SyncRun, subject: str) -> dict[str, list[str]]:
    """What each short text field holds today, so the assistant writes values that exist."""
    found: dict[str, list[str]] = {}
    for name, f in FIELDS[subject].items():
        if f.kind != "text" or name in ("lines_text", "email_subject", "job_name", "number"):
            continue
        column = f.sql(run.as_of).label("v")
        query = base(subject, run).with_only_columns(column).distinct().limit(40)
        values = [v for v in await db.scalars(query) if v]
        if values:
            found[name] = sorted(values)
    return found


async def run_rule(db: AsyncSession, run: SyncRun, issue_type: IssueType, rule: Rule | None = None) -> list[Finding]:
    """Run one rule over this sync's records and return what it finds, as the built-in checks do."""
    subject = issue_type.subject or "job"
    rule = validate(rule or Rule.model_validate(issue_type.rule), subject)
    fields = FIELDS[subject]
    tests = [_test(c, fields, run.as_of) for c in rule.conditions]
    shown = list(dict.fromkeys([c.field for c in rule.conditions] + [c.other_field for c in rule.conditions if c.other_field]))
    amount = fields[rule.amount_field].sql(run.as_of) if rule.amount_field else literal(0)
    query = base(subject, run).add_columns(
        type_coerce(func.coalesce(amount, 0), Job.contract_value.type).label("amount"),
        *(fields[name].sql(run.as_of).label(f"f_{name}") for name in shown),
    ).where(and_(*tests) if rule.match == "all" else or_(*tests))

    found = []
    for r in await db.execute(query):
        detail = ". ".join(f"{fields[name].label}: {_value_words(fields[name], getattr(r, f'f_{name}'))}" for name in shown)
        found.append(
            Finding(
                issue_type.key, r.subject, Decimal(r.amount or 0),
                summary=issue_type.title, detail=f"{detail}.",
                next_step="Look into it and say what is behind it.", action_label="Ask about it",
                owner=r.owner, job_id=r.job_id, document=r.document, evidence=[r.line_id] if r.line_id else [],
            )
        )
    return found
