"""Sync step 2: build the job-centred model from the landed rows.

Reads only from `raw.source_record`, never from the source systems, so it
can be re-run on its own when the mapping rules change.

Rows are upserted on their natural keys, which keeps our ids stable from one
sync to the next. Anything not seen in this run is removed at the end.
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, CostCodeMap, Job, JobOwner, MoneyLine, SourceRecord, SyncRun

OWNER_ROLES = {"Primary Ops Manager": "ops_manager", "Primary AE": "account_executive"}

# The ledger books every job cost to one account. The chart of accounts calls
# it internal labour and the cost code list calls it materials, so we do not
# guess a category for it.
UNCLASSIFIED = "UNCLASSIFIED"


def to_date(value) -> date | None:
    return date.fromisoformat(value[:10]) if value else None


def to_money(value) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def canonical_category(code: str | None) -> str | None:
    """`internal-labor` and `INTERNAL_LABOR` are the same category."""
    return code.upper().replace("-", "_") if code else None


class Landed:
    """The rows landed in this run, grouped by source table."""

    def __init__(self) -> None:
        self._by_table: dict[str, list[tuple[int, dict]]] = defaultdict(list)

    @classmethod
    async def load(cls, db: AsyncSession, run: SyncRun) -> "Landed":
        landed = cls()
        query = select(SourceRecord.id, SourceRecord.table_name, SourceRecord.payload).where(
            SourceRecord.last_seen_run_id == run.id
        )
        for record_id, table, payload in await db.execute(query):
            landed._by_table[table].append((record_id, payload))
        return landed

    def rows(self, table: str) -> list[tuple[int, dict]]:
        return self._by_table.get(table, [])

    def by_id(self, table: str) -> dict[str, dict]:
        return {p["id"]: p for _, p in self.rows(table)}


async def _upsert(db: AsyncSession, model, rows: list[dict], key: list[str]) -> None:
    if not rows:
        return
    statement = insert(model).values(rows)
    updatable = {c: statement.excluded[c] for c in rows[0] if c not in key}
    await db.execute(statement.on_conflict_do_update(index_elements=key, set_=updatable))


async def normalize(db: AsyncSession, run: SyncRun) -> dict:
    landed = await Landed.load(db, run)

    # --- Companies: customers and vendors in one table -----------------------
    vendor_ref = {p["company_id"]: p["legacy_vendor_id"] for _, p in landed.rows("vendor_accounts")}
    discount = {p["company_id"]: p for _, p in landed.rows("vendor_discount_terms")}
    await _upsert(
        db,
        Company,
        [
            {
                "source_id": p["id"],
                "name": p["name"],
                "is_customer": bool(p["is_customer"]),
                "is_vendor": bool(p["is_vendor"]),
                "vendor_ref": vendor_ref.get(p["id"]),
                "discount_pct": to_money(discount.get(p["id"], {}).get("discount_percentage")),
                "discount_days": discount.get(p["id"], {}).get("discount_days"),
                "source_record_id": record_id,
                "sync_run_id": run.id,
            }
            for record_id, p in landed.rows("companies")
        ],
        ["source_id"],
    )
    company_id = dict((await db.execute(select(Company.source_id, Company.id))).all())

    # --- Jobs: each project joined to the opportunity it came from -----------
    opportunities = {p["id"]: (record_id, p) for record_id, p in landed.rows("opportunities")}
    contacts = landed.by_id("contacts")
    branches = landed.by_id("branches")
    budget_by_opp = {p["opportunity_id"]: p for _, p in landed.rows("budgets")}
    first_change_order: dict[str, dict] = {}
    for _, p in sorted(landed.rows("change_orders"), key=lambda r: r[1]["change_order_number"]):
        first_change_order.setdefault(p["project_id"], p)

    job_rows = []
    for record_id, project in landed.rows("projects"):
        opp_record_id, opp = opportunities[project["opportunity_id"]]
        contact = contacts.get(opp.get("contact_id") or "", {})
        branch = branches.get(opp.get("operating_branch_id") or "", {})
        budget = budget_by_opp.get(opp["id"], {})
        change_order = first_change_order.get(project["id"])
        job_rows.append(
            {
                "job_number": project["project_number"],
                "name": opp.get("site_name") or project["project_number"],
                "customer_id": company_id.get(contact.get("company_id")),
                "service_line": project.get("project_type"),
                "branch": branch.get("name"),
                "crm_status": opp.get("status"),
                "stage": project["status"],
                "won_on": to_date(opp.get("won_date")),
                "estimated_value": to_money(opp.get("estimated_value")),
                "contract_value": to_money(project.get("contract_value")) or Decimal(0),
                "original_contract_value": to_money(change_order["original_contract_value"]) if change_order else None,
                "planned_margin_pct": to_money(project.get("default_profit_margin")),
                "budget": to_money(budget.get("total_budget_amount")) or Decimal(0),
                "on_site_on": to_date(project.get("first_day_on_site")),
                "planned_finish_on": to_date(project.get("estimated_completion_date")),
                "completed_on": to_date(project.get("completed_at") or project.get("actual_completion_date")),
                "closed_on": to_date(project.get("closed_at")),
                "cancelled_on": to_date(project.get("cancelled_date")),
                "opportunity_record_id": opp_record_id,
                "project_record_id": record_id,
                "sync_run_id": run.id,
            }
        )
    await _upsert(db, Job, job_rows, ["job_number"])
    job_id_by_number = dict((await db.execute(select(Job.job_number, Job.id))).all())
    job_id_by_opp = {
        project["opportunity_id"]: job_id_by_number[project["project_number"]]
        for _, project in landed.rows("projects")
    }

    # --- Owners --------------------------------------------------------------
    employees = landed.by_id("employees")
    await db.execute(delete(JobOwner))
    owner_rows = {}
    for _, p in landed.rows("engagement_assignments"):
        role = OWNER_ROLES.get(p["capacity"])
        job_id = job_id_by_opp.get(p["opportunity_id"])
        employee = employees.get(p["employee_id"])
        if role and job_id and employee:
            owner_rows[(job_id, role)] = {
                "job_id": job_id,
                "role": role,
                "name": employee["display_name"],
                "email": employee.get("email"),
            }
    if owner_rows:
        await db.execute(insert(JobOwner).values(list(owner_rows.values())))

    # --- Cost code crosswalk -------------------------------------------------
    await db.execute(delete(CostCodeMap))
    crosswalk: dict[tuple[str, str], dict] = {}
    for _, p in landed.rows("cost_codes"):
        crosswalk[("accounting", p["code"])] = {"category": canonical_category(p["code"]), "note": p.get("name")}
    for table in ("actual_costs", "budget_lines"):
        for _, p in landed.rows(table):
            if p.get("cost_code"):
                crosswalk.setdefault(("project", p["cost_code"]), {"category": canonical_category(p["cost_code"]), "note": None})
    for _, p in landed.rows("gl_entries"):
        account = p.get("account_no") or ""
        if account.startswith("5"):
            crosswalk.setdefault(
                ("ledger", account),
                {"category": UNCLASSIFIED, "note": "The ledger books all job cost to this one account"},
            )
    if crosswalk:
        await db.execute(
            insert(CostCodeMap).values(
                [{"source_system": s, "source_code": c, **v} for (s, c), v in sorted(crosswalk.items())]
            )
        )

    # --- Money lines: every dollar, in one shape -----------------------------
    lines: list[dict] = []

    def line(kind, table, record_id, p, *, amount, opp_id=None, company=None, **fields):
        lines.append(
            {
                "kind": kind,
                "job_id": job_id_by_opp.get(opp_id) if opp_id else None,
                "company_id": company_id.get(company) if company else None,
                "doc_number": None,
                "description": None,
                "amount": to_money(amount) or Decimal(0),
                "paid_amount": Decimal(0),
                "line_date": None,
                "due_date": None,
                "status": None,
                "cost_category": None,
                "source_table": table,
                "source_pk": str(p["id"]),
                "source_record_id": record_id,
                "sync_run_id": run.id,
                **fields,
            }
        )

    for record_id, p in landed.rows("actual_costs"):
        line(
            "ops_cost", "actual_costs", record_id, p,
            amount=p["amount"], opp_id=p.get("opportunity_id"), company=p.get("vendor_id"),
            description=p.get("item_name"), line_date=to_date(p.get("cost_date")),
            cost_category=canonical_category(p.get("cost_code")),
        )

    for record_id, p in landed.rows("gl_entries"):
        account = p.get("account_no") or ""
        if p.get("entry_type") == "AR_BILLING":
            kind = "ledger_receivable"
        elif p.get("entry_type") == "AR_COLLECTION":
            kind = "ledger_receipt"
        elif account.startswith("5"):
            kind = "ledger_cost"
        elif account.startswith("4"):
            kind = "ledger_revenue"
        else:
            continue
        line(
            kind, "gl_entries", record_id, p,
            amount=p["amount"], opp_id=p.get("opportunity_id"),
            doc_number=p.get("document_number"), description=f"Account {account}",
            line_date=to_date(p.get("posting_date")), due_date=to_date(p.get("due_date")),
            status=p.get("source_status"),
            cost_category=UNCLASSIFIED if kind == "ledger_cost" else None,
        )

    for record_id, p in landed.rows("ap_invoices"):
        line(
            "vendor_bill", "ap_invoices", record_id, p,
            amount=p["amount"], opp_id=p.get("opportunity_id"), company=p.get("vendor_id"),
            doc_number=p.get("invoice_number"), description=p.get("vendor_name"),
            paid_amount=to_money(p.get("total_paid_amount")) or Decimal(0),
            line_date=to_date(p.get("invoice_date")), due_date=to_date(p.get("due_date")),
            status=p.get("status"), cost_category=canonical_category(p.get("cost_code")),
        )

    invoices = landed.by_id("ar_invoices")
    paid_by_invoice: dict[str, Decimal] = defaultdict(Decimal)
    for _, p in landed.rows("ar_payments"):
        paid_by_invoice[p["invoice_id"]] += to_money(p["amount"])

    for record_id, p in landed.rows("ar_invoices"):
        line(
            "customer_invoice", "ar_invoices", record_id, p,
            amount=p["total"], opp_id=p.get("opportunity_id"), company=p.get("company_id"),
            doc_number=p.get("invoice_number"), paid_amount=paid_by_invoice.get(p["id"], Decimal(0)),
            line_date=to_date(p.get("invoice_date")), due_date=to_date(p.get("due_date")),
            status=p.get("status"),
        )

    for record_id, p in landed.rows("ar_payments"):
        invoice = invoices.get(p["invoice_id"], {})
        line(
            "customer_payment", "ar_payments", record_id, p,
            amount=p["amount"], opp_id=invoice.get("opportunity_id"), company=invoice.get("company_id"),
            doc_number=invoice.get("invoice_number"), description=p.get("reference_number"),
            line_date=to_date(p.get("payment_date")), status=p.get("payment_method"),
        )

    await _upsert(db, MoneyLine, lines, ["source_table", "source_pk"])

    # --- Remove anything the source no longer has ----------------------------
    removed = 0
    for model in (MoneyLine, Job, Company):
        removed += (await db.execute(delete(model).where(model.sync_run_id != run.id))).rowcount
    await db.flush()

    return {
        "companies": len(company_id),
        "jobs": len(job_rows),
        "owners": len(owner_rows),
        "money_lines": len(lines),
        "removed": removed,
    }
