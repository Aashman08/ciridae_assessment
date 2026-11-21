# Sync

| File | Step |
| --- | --- |
| `connector.py` | Reads rows from the source systems (today, the export) |
| `landing.py` | 1. Land |
| `normalize.py` | 2. Normalize |
| `financials.py` | 3. Total |
| `scheduler.py` | Runs a sync every `SYNC_EVERY_MINUTES`, and once at startup if none has run |

Step 4, finding issues, is in [../checks](../checks/README.md).

`POST /api/v1/sync-runs` reads from Harborstone's database and writes only
to the app's own. It runs four steps in one transaction.

1. **Land.** Every row of the 42 exported tables is copied into
   `raw.source_record` as JSON, with its system, table, key and a content
   hash. A row is rewritten only when its hash changes.
2. **Normalize.** Each project is joined to its opportunity, customer,
   branch, budget and owners to make a job. Every cost entry, ledger entry,
   vendor bill, invoice and payment becomes one *money line* that points to
   the source row it came from. Notes written in the project system and on
   invoices in accounting are copied in with their job and invoice.
3. **Total.** Per job: contract, budget, cost three ways, revenue from ledger
   to cash, owed and past due. Stored once per sync so runs can be compared.
4. **Find issues.** Seventeen built-in checks compare the systems, and any checks people added run in the same step. Each finding has a
   stable key, so re-syncing keeps its owner, comments and resolution.
