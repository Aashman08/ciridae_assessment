"""Where source rows come from.

In production there would be one connector per system, each calling that
system's API. For the demo a single connector reads the provided export from
Harborstone's database, over a read-only connection. The rest of the pipeline
only sees the `Connector` interface, so swapping in live connectors changes
nothing else.
"""

from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

# Which system each exported table belongs to. The export does not say, so
# this is our reading of the company brief and the legacy_* column names.
SYSTEM_BY_TABLE: dict[str, str] = {
    **dict.fromkeys(
        [
            "companies", "contacts", "contact_interactions", "contact_addresses",
            "addresses", "industries", "opportunities", "opportunity_documents",
            "bids", "catastrophe_events", "company_documents",
        ],
        "crm",
    ),
    **dict.fromkeys(
        [
            "projects", "project_notes", "project_documents", "budgets",
            "budget_lines", "actual_costs", "change_orders", "work_authorizations",
            "engagement_assignments", "employees", "branches", "documents",
            "standard_tasks", "commission_policies",
        ],
        "project",
    ),
    **dict.fromkeys(
        [
            "ap_invoices", "ap_invoice_lines", "ar_invoices", "ar_invoice_lines",
            "ar_invoice_notes", "ar_invoice_documents", "ar_payments", "gl_entries",
            "gl_accounts", "cost_codes", "accounting_periods", "legal_entities",
            "vendor_accounts", "vendor_discount_terms", "inbound_emails",
            "inbound_email_attachments",
        ],
        "accounting",
    ),
    "dataset_metadata": "export",
}

# Every table is keyed on `id` except this one.
PK_OVERRIDES = {"dataset_metadata": "key"}


class Connector(Protocol):
    async def tables(self) -> list[str]: ...

    async def rows(self, table: str) -> list[tuple[str, dict]]:
        """Return (primary key, row as a dict) for every row in the table."""
        ...

    async def metadata(self, key: str) -> str | None:
        """A fact about the export itself, such as the date it was taken."""
        ...


class ExportConnector:
    """Reads the provided export from Harborstone's database."""

    def __init__(self, engine: AsyncEngine, schema: str) -> None:
        self.engine = engine
        self.schema = schema

    async def tables(self) -> list[str]:
        async with self.engine.connect() as connection:
            found = await connection.execute(
                text(
                    "select table_name from information_schema.tables "
                    "where table_schema = :schema and table_type = 'BASE TABLE' order by table_name"
                ),
                {"schema": self.schema},
            )
            return list(found.scalars())

    async def rows(self, table: str) -> list[tuple[str, dict]]:
        pk = PK_OVERRIDES.get(table, "id")
        # Table names come from information_schema above, never from a caller.
        async with self.engine.connect() as connection:
            result = await connection.execute(text(f'select to_jsonb(t) from "{self.schema}"."{table}" t'))
            return [(str(payload[pk]), payload) for (payload,) in result]

    async def metadata(self, key: str) -> str | None:
        async with self.engine.connect() as connection:
            result = await connection.execute(
                text(f'select value from "{self.schema}".dataset_metadata where key = :key'), {"key": key}
            )
            return result.scalar()
