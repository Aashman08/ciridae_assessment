"""Checks people add, written as rules over fixed fields.

A rule names fields from a fixed list for one kind of record (a job, a customer
invoice or a vendor bill), compares each with a value or with another field, and
says whether all or any of those tests must hold. Our code compiles it to one SQL
query and runs it on every sync, next to the built-in checks in `issues.py`, and
its findings become issues the same way theirs do. No model is involved in running
a rule; a model only helps write one, and what it writes is checked here first.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Callable

from sqlalchemy import Date, Integer, and_, func, literal, or_, select, type_coerce
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import InvalidRequestError
from app.issues import OPS_MANAGER, OWNER, VENDOR_NAME, Finding, customer, fin, line, money, vendor
from app.models import IssueType, Job, SyncRun
from app.schemas import Rule, RuleCondition

NUMBERS = ("money", "number", "days")


@dataclass(frozen=True)
class FactField:
    label: str
    kind: str  # money | number | days | text | bool
    sql: Callable[[date], object]
    about: str


def _days_since(column):
    return lambda as_of: type_coerce(literal(as_of, Date) - column, Integer)


def _days_until(column):
    return lambda as_of: type_coerce(column - literal(as_of, Date), Integer)


def _const(expression):
    return lambda as_of: expression


JOB_FIELDS: dict[str, FactField] = {
    "contract_value": FactField("Contract value", "money", _const(Job.contract_value), "The contract value in the project system"),
    "budget": FactField("Budget", "money", _const(Job.budget), "The job's cost budget"),
    "estimated_value": FactField("Estimated value", "money", _const(Job.estimated_value), "The value estimated in the CRM when won"),
    "ops_cost": FactField("Cost logged by the project team", "money", _const(fin.ops_cost), "Cost entered in the project system"),
    "ledger_cost": FactField("Cost in the ledger", "money", _const(fin.ledger_cost), "Job cost finance has booked"),
    "ledger_revenue": FactField("Revenue in the ledger", "money", _const(fin.ledger_revenue), "Revenue finance has booked"),
    "invoiced": FactField("Invoiced", "money", _const(fin.invoiced), "Every invoice raised, sent or not"),
    "collected": FactField("Collected", "money", _const(fin.collected), "Cash received from the customer"),
    "owed": FactField("Owed by the customer", "money", _const(fin.owed), "Sent and not yet paid"),
    "past_due": FactField("Past due", "money", _const(fin.past_due), "Owed and past its due date"),
    "unpaid_bills": FactField("Unpaid vendor bills", "money", _const(fin.unpaid_bills), "Vendor bills on the job not yet paid"),
    "stage": FactField("Stage", "text", _const(Job.stage), "WON, IN_PROGRESS, COMPLETED, CLOSED or CANCELLED"),
    "kind_of_work": FactField("Kind of work", "text", _const(Job.service_line), "MITIGATION, ROOFING, CONSTRUCTION, BUILD_BACK and so on"),
    "branch": FactField("Branch", "text", _const(Job.branch), "The branch running the job"),
    "urgent": FactField("Urgent", "bool", _const(Job.urgent_reason.is_not(None)), "Mitigation work or a named catastrophe"),
    "has_ops_manager": FactField("Has an ops manager", "bool", _const(OPS_MANAGER.is_not(None)), "An ops manager is named for the job"),
    "days_since_won": FactField("Days since won", "days", _days_since(Job.won_on), "Days from the win to the date of the figures"),
    "days_since_on_site": FactField("Days since on site", "days", _days_since(Job.on_site_on), "Days since the crew was first on site"),
    "days_to_planned_finish": FactField("Days to planned finish", "days", _days_until(Job.planned_finish_on), "Negative once the planned finish has passed"),
}

DOCUMENT_FIELDS: dict[str, FactField] = {
    "amount": FactField("Amount", "money", _const(line.amount), "The document's total"),
    "paid": FactField("Paid", "money", _const(line.paid_amount), "Paid against it so far"),
    "open_amount": FactField("Open amount", "money", _const(line.amount - line.paid_amount), "Total less paid"),
    "status": FactField("Status", "text", _const(line.status), "Its status in accounting, such as SENT, APPROVED, DRAFT, POSTED"),
    "days_past_due": FactField("Days past due", "days", _days_since(line.due_date), "Negative while it is not yet due"),
    "days_since_dated": FactField("Days since dated", "days", _days_since(line.line_date), "Days since its date"),
    "job_stage": FactField("Job stage", "text", _const(Job.stage), "The stage of the job it is on"),
}

INVOICE_FIELDS = {
    **DOCUMENT_FIELDS,
    "customer": FactField("Customer", "text", _const(func.coalesce(customer.name, "")), "The customer's name"),
}
BILL_FIELDS = {
    **DOCUMENT_FIELDS,
    "vendor": FactField("Vendor", "text", _const(VENDOR_NAME), "The vendor's name"),
    "has_job": FactField("Is on a job", "bool", _const(line.job_id.is_not(None)), "The bill is assigned to a job"),
    "cost_code": FactField("Cost code", "text", _const(func.coalesce(line.cost_category, "")), "Its cost code"),
}

FIELDS: dict[str, dict[str, FactField]] = {"job": JOB_FIELDS, "customer_invoice": INVOICE_FIELDS, "vendor_bill": BILL_FIELDS}
SUBJECT_WORDS = {"job": "job", "customer_invoice": "customer invoice", "vendor_bill": "vendor bill"}
OPS_WORDS = {">": "is more than", ">=": "is at least", "<": "is less than", "<=": "is at most", "=": "is", "!=": "is not"}


def catalogue(subject: str) -> list[dict]:
    """The fields a rule may use for one kind of record, as the model is shown them."""
    return [{"field": name, "label": f.label, "type": f.kind, "meaning": f.about} for name, f in FIELDS[subject].items()]


def validate(rule: Rule, subject: str) -> Rule:
    """A rule may only name fields that exist for its kind of record, and compare like with like."""
    fields = FIELDS[subject]
    for c in rule.conditions:
        f = fields.get(c.field)
        if f is None:
            raise InvalidRequestError(f"'{c.field}' is not a field a {SUBJECT_WORDS[subject]} check can use.")
        if c.other_field is not None:
            other = fields.get(c.other_field)
            if other is None or (other.kind in NUMBERS) != (f.kind in NUMBERS) or other.kind in ("text", "bool"):
                raise InvalidRequestError(f"'{c.field}' cannot be compared with '{c.other_field}'.")
            if f.kind not in NUMBERS:
                raise InvalidRequestError(f"'{c.field}' can only be compared with a value.")
            continue
        if c.value is None:
            raise InvalidRequestError(f"The test on '{c.field}' needs a value to compare with.")
        if f.kind in NUMBERS and (isinstance(c.value, bool) or not isinstance(c.value, (int, float))):
            raise InvalidRequestError(f"'{c.field}' is a number, so it must be compared with a number.")
        if f.kind == "text" and (not isinstance(c.value, str) or c.op not in ("=", "!=")):
            raise InvalidRequestError(f"'{c.field}' is text: it can only be equal or not equal to a word.")
        if f.kind == "bool" and (not isinstance(c.value, bool) or c.op not in ("=", "!=")):
            raise InvalidRequestError(f"'{c.field}' is yes or no: compare it with true or false.")
    if rule.amount_field is not None and fields.get(rule.amount_field, FactField("", "", _const(None), "")).kind != "money":
        raise InvalidRequestError(f"'{rule.amount_field}' is not a money field.")
    return rule


def _value_words(f: FactField, value) -> str:
    if f.kind == "money":
        return money(Decimal(str(value)))
    if f.kind == "days":
        return f"{value:g} days"
    if f.kind == "bool":
        return "yes" if value else "no"
    if f.kind == "text":
        return str(value).replace("_", " ").lower()
    return f"{value:g}"


def in_words(rule: Rule, subject: str) -> str:
    """The rule as a sentence a person can check: "Flags a customer invoice where open amount is more than $100,000 and …"."""
    fields = FIELDS[subject]
    parts = []
    for c in rule.conditions:
        f = fields[c.field]
        if c.other_field:
            other = fields[c.other_field].label.lower()
            scaled = f"{c.times * 100:g}% of {other}" if c.times not in (None, 1) else other
            parts.append(f"{f.label.lower()} {OPS_WORDS[c.op]} {scaled}")
        else:
            parts.append(f"{f.label.lower()} {OPS_WORDS[c.op]} {_value_words(f, c.value)}")
    joiner = " and " if rule.match == "all" else " or "
    return f"Flags a {SUBJECT_WORDS[subject]} where " + joiner.join(parts)


def _test(c: RuleCondition, fields: dict[str, FactField], as_of: date):
    left = fields[c.field].sql(as_of)
    if c.other_field:
        right = fields[c.other_field].sql(as_of)
        if c.times not in (None, 1):
            right = right * Decimal(str(c.times))
    elif fields[c.field].kind == "text":
        left, right = func.upper(left), str(c.value).upper()
    else:
        right = c.value if isinstance(c.value, bool) else Decimal(str(c.value))
    return {
        ">": left > right, ">=": left >= right, "<": left < right, "<=": left <= right, "=": left == right, "!=": left != right,
    }[c.op]


def _base(subject: str, run: SyncRun):
    """One row per record of this kind, with who owns it and how to name it."""
    if subject == "job":
        return select(
            Job.id.label("job_id"), Job.job_number, Job.name.label("job_name"), Job.job_number.label("subject"),
            OWNER, literal(None).label("line_id"), literal(None).label("document"),
        ).join(fin, and_(fin.job_id == Job.id, fin.sync_run_id == run.id))
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


async def run_rule(db: AsyncSession, run: SyncRun, issue_type: IssueType, rule: Rule | None = None) -> list[Finding]:
    """Run one rule over this sync's records and return what it finds, as the built-in checks do."""
    subject = issue_type.subject or "job"
    rule = validate(rule or Rule.model_validate(issue_type.rule), subject)
    fields = FIELDS[subject]
    tests = [_test(c, fields, run.as_of) for c in rule.conditions]
    shown = list(dict.fromkeys([c.field for c in rule.conditions] + [c.other_field for c in rule.conditions if c.other_field]))
    amount = fields[rule.amount_field].sql(run.as_of) if rule.amount_field else literal(0)
    query = _base(subject, run).add_columns(
        type_coerce(amount, Job.contract_value.type).label("amount"),
        *(fields[name].sql(run.as_of).label(f"f_{name}") for name in shown),
    ).where(and_(*tests) if rule.match == "all" else or_(*tests))
    if subject == "job":
        query = query.where(Job.stage != "CANCELLED")

    found = []
    for r in await db.execute(query):
        detail = ". ".join(
            f"{fields[name].label}: {_value_words(fields[name], getattr(r, f'f_{name}'))}"
            if getattr(r, f"f_{name}") is not None else f"{fields[name].label}: not recorded"
            for name in shown
        )
        found.append(
            Finding(
                issue_type.key, r.subject, Decimal(r.amount or 0),
                summary=issue_type.title, detail=f"{detail}.",
                next_step="Look into it and say what is behind it.", action_label="Ask about it",
                owner=r.owner, job_id=r.job_id, document=r.document, evidence=[r.line_id] if r.line_id else [],
            )
        )
    return found
