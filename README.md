# Harborstone Reconciliation

A reconciliation service for Harborstone, built for the Ciridae case study.

Harborstone runs on a CRM, a project management system and an accounting
system that were never designed as one workflow. This service joins them into one
record per job and reports where they disagree, so that nobody has to
reconcile a job by hand to know whether it is finished and what it earned.

The repository holds the **backend** (`backend/`), which does the
reconciliation and serves an API, and the **web app** (`frontend/`), which
uses only that API.

## Who it is for

- **Rachel Kim, VP of Finance.** She needs profit and cash figures per job
  that tie back to source records, with every disagreement in view.
- **Tasha Green, Project Director.** Her team does the follow-ups. She needs
  a short list of what is stuck on her jobs, largest first, with a next step.

Both read the same data. Tasha's view is Rachel's, filtered to her jobs.

## Run it

Requires Postgres 15+, Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
# 1. Restore Harborstone's export (skip if that database already exists)
createdb harborstone
psql -d harborstone -f source_data.sql

# 2. Start the API. This creates our database and .env if they are missing,
#    and applies any pending migrations on startup.
cd backend
./run.sh

# 3. In a second terminal, start the web app
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The first screen offers to run the first sync;
after that, use **Sync now** in the top bar. Interactive API docs are at
http://localhost:8000/docs.

If port 8000 is taken, run the API elsewhere and tell the web app where:

```bash
cd backend && uv run uvicorn app.server:app --port 8010
cd frontend && API_URL=http://localhost:8010 npm run dev
```

Settings are read from `backend/.env` (copied from `.env.example`):

| Variable | Example | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+psycopg:///harborstone_recon` | Our own database. Everything this service writes goes here |
| `SOURCE_DATABASE_URL` | `postgresql+psycopg:///harborstone` | Harborstone's database with the export. Opened read-only |
| `SOURCE_SCHEMA` | `source_company` | Schema holding the export |
| `API_KEY` | not set | When set, every `/api/v1` request must send it as `X-API-Key` |
| `OPENAI_API_KEY` | not set | Turns on Ask. Without it everything else works and Ask says it is not set up |
| `ASK_MODEL` | not set | Model for Ask. Empty uses the OpenAI Agents SDK default |

## Tests

```bash
cd backend && uv run pytest
```

91 tests. Each run builds two databases of its own, `harborstone_test` from
`source_data.sql` and an empty `harborstone_recon_test`, so the working
databases are never touched. Every test module starts with our tables empty.
Expected figures are tied to the export: for example $3,174,100 invoiced,
$1,696,536 collected and 62 issues as of 28 July 2026.

## Code layout

Everything is in `backend/app/`, one job per file.

| File | Job |
| --- | --- |
| `server.py` | Creates the app; registers routes, middleware and error handlers |
| `endpoints.py` | The routes, and nothing else. Each opens a client with `async with` and awaits one method |
| `client.py` | Every operation. Owns the session and transaction for one request |
| `database.py` | Settings, both engines, migrations at startup |
| `models.py`, `schemas.py`, `serializers.py` | Tables, API contracts, and the conversion between them |
| `connector.py` | Reads rows from the source systems |
| `landing.py`, `normalize.py`, `financials.py`, `issues.py` | The four steps of a sync, in order |
| `errors.py`, `exception_handlers.py`, `middleware.py` | Typed errors, one error format, request IDs, optional API key |

All database access is async. Schema changes go through Alembic migrations,
which record what has been applied in `recon.alembic_version`.

## The web app

React, TypeScript, Vite and Tailwind, in `frontend/src/`.

| Screen | What it is for |
| --- | --- |
| Ask | Type a question in plain words. The answer comes with the records it rests on and the lookups that produced it |
| Overview | Finance sees cash owed, invoices not sent, unpaid bills, contract-to-cash totals and issues by type. An ops manager sees their own to-do list, largest first |
| Jobs | Every job with the figures each system holds for it |
| Job | Revenue and cost figures side by side. Pick one of each and the profit and margin for that pair appear beside them |
| Issues | The work queue. **Log update** on a row records what someone has already done. It never contacts anyone or changes an invoice or bill. A note keeps the issue open; resolving is a separate choice |
| Issue | What is wrong, what to do, the records behind it and the untouched source row for each, plus its history |
| Customer invoices, Vendor bills | Every invoice and bill across jobs |
| Issue types | The thirteen checks, with an on/off switch and tolerance for each |

| Folder | Holds |
| --- | --- |
| `lib/` | `api.ts` (every call to the backend and the shapes it returns), formatting, who is viewing, sync |
| `components/` | The app shell, the two shared tables, the resolve dialog and small building blocks |
| `pages/` | One file per screen |

The browser only talks to the Vite dev server, which passes `/api` on to the
backend. Filters and paging live in the address bar, so a filtered list can be
bookmarked. The design follows the unslop skill by Damir Sokolovsky
(@heydamir): one grey ramp, one accent spent only on what needs a person, a 4px
grid, one icon set, and figures set in a mono face so digits line up.

## How a sync works

`POST /api/v1/sync-runs` reads from Harborstone's database and writes only
to ours. It runs four steps in one transaction.

1. **Land.** Every row of the 42 exported tables is copied into
   `raw.source_record` as JSON, with its system, table, key and a content
   hash. A row is rewritten only when its hash changes.
2. **Normalize.** Each project is joined to its opportunity, customer,
   branch, budget and owners to make a job. Every cost entry, ledger entry,
   vendor bill, invoice and payment becomes one *money line* that points to
   the source row it came from.
3. **Total.** Per job: contract, budget, cost three ways, revenue from ledger
   to cash, owed and past due. Stored once per sync so runs can be compared.
4. **Find issues.** Thirteen checks compare the systems. Each finding has a
   stable key, so re-syncing keeps its owner, comments and resolution.

Our tables sit in two schemas of the `harborstone_recon` database. Harborstone's
database is a separate one, and the connection to it is read-only:

| Schema | Tables |
| --- | --- |
| `raw` | `source_record` |
| `recon` | `sync_run`, `company`, `job`, `job_owner`, `cost_code_map`, `money_line`, `job_financials`, `issue_type`, `issue`, `issue_evidence`, `issue_event`, `ask_exchange` |

## API

All under `/api/v1`. List endpoints take `limit` and `offset` and return
`{"data": [...], "total": n, "has_more": bool}`. Amounts are decimal strings
such as `"246300.00"`. Errors always look like
`{"error": {"type", "message", "request_id"}}`, and every response carries an
`X-Request-ID` header.

| Method | Path | What it does |
| --- | --- | --- |
| POST | `/sync-runs` | Run a sync. Optional `as_of` date |
| GET | `/sync-runs`, `/sync-runs/{id}` | Past runs and what each did |
| GET | `/summary` | Cash position, contract-to-cash totals, issues by type. `owner` filters to one ops manager |
| GET | `/jobs` | Jobs with figures from each system. Filter by `stage`, `owner`, `branch`, `has_issues` |
| GET | `/jobs/{number}` | One job: revenue and cost figures side by side, and profit for the `revenue` and `cost` pair chosen |
| GET | `/jobs/{number}/lines` | Every money line on the job |
| GET | `/lines?kind=` | Invoices or vendor bills across jobs |
| GET | `/issues` | The work queue, largest first. Filter by `type`, `owner`, `status`, `severity`, `job` |
| GET | `/issues/{id}` | One issue with its evidence and history |
| POST | `/issues/{id}/actions` | Assign, comment, resolve or reopen |
| GET | `/customer-balances` | What each customer owes, largest first |
| POST | `/ask` | Ask a question in plain words. Returns the answer as plain text (`answer`) and laid out for display (`spec`), the lookups used and the records it rests on, and saves the exchange |
| GET, DELETE | `/ask/history?asked_by=` | Read or clear one person's saved conversation |
| GET | `/issue-types` | The checks, their settings and what each has found |
| PATCH | `/issue-types/{key}` | Switch a check off or change its tolerance |
| GET | `/source-records/{id}` | The untouched source row behind any number |

## Ask: where AI is used, and where it is not

The figures and the thirteen checks are fixed logic, so the same data always
gives the same answer and every number can be traced. AI is used for one thing:
answering questions about that data in plain words.

It is built on the OpenAI Agents SDK, in `backend/app/assistant.py`.

- **The model cannot query the database.** It can only choose one of nine
  tools and fill in that tool's typed inputs. Our code checks the inputs and
  runs the query.
- **Each tool is an existing operation** on the same client the API uses, so
  an answer's figures are the app's figures.
- **Scope is enforced in our code.** Someone who sees only their own jobs
  gets only those, whatever the model asks for.
- **Answers show their working.** Each comes back with the lookups used and
  the jobs, invoices and issues it rests on.
- **Figures are checked in our code.** Every dollar figure in an answer is
  compared with what the tools returned. Any the assistant calculated itself
  (a sum or a difference) is listed separately, and an incomplete figure such
  as "$113,?" is sent back once and then refused.
- **Read-only.** No tool changes anything.
- **The answer's layout is fixed too.** The model must reply with a list of
  blocks from a set of four (text, table, figures, and a line or bar chart), checked against a schema
  before we see it; anything else is refused. The API returns them as a
  [json-render](https://json-render.dev) spec, and the web app draws that spec
  with its own components, so a table in an answer is the same table as
  everywhere else. A chart is drawn by the app from the numbers in the block;
  for anything by month those numbers come from a fixed SQL total
  (`totals_by_month`), not from the model adding up invoices. Figures inside tables go through the same check as figures
  in sentences.
- **Conversations are saved per person** in `recon.ask_exchange`, so a
  conversation is still there after leaving the page or reloading. The last six
  exchanges are given to the model so a follow-up question makes sense.
- **Nothing is uploaded as a trace.** SDK tracing is switched off.

| Tool | What it returns |
| --- | --- |
| `company_summary` | Cash owed, past due, unsent invoices, unpaid bills, contract-to-cash totals, issues by type |
| `list_jobs` | Jobs with each system's figures. Inputs: stage, branch, has_issues, limit |
| `get_job` | One job in full, with profit for a chosen revenue and cost figure |
| `list_issues` | Issues, largest first. Inputs: issue_type, severity, job_number, status, limit |
| `list_issue_types` | What each check looks for and what it has found |
| `list_invoices` | Customer invoices, largest unpaid first |
| `list_vendor_bills` | Vendor bills, largest unpaid first. Input: no_job |
| `owed_by_customer` | What each customer owes and how much is past due |

Adding a capability means adding a tool with fixed inputs. There is no tool
that accepts SQL, a table name or a free-form filter.

## Design decisions

- **Our own database, source left read-only.** The joined record, the
  totals, the issues and their history have no home in the three systems.
  This service keeps them in a separate database and opens Harborstone's with a
  read-only connection, so nothing here can change their data.
- **Three layers, each rebuildable from the one before.** Changing a rule
  means re-running from `raw`, not calling the source again.
- **Every number keeps its source.** An issue cites money lines; a money line
  cites a source record.
- **No silent winner on cost.** Each job has a cost per the project team, a
  cost per the ledger, and unpaid vendor bills. Nothing in the data links a
  cost entry to a bill, so they are reported as three figures and profit is
  computed only for a pair the reader picks. "Ledger + unpaid bills" is
  labelled an upper bound.
- **Checks are data.** Tolerances and on/off switches live in `issue_type`
  and can be changed through the API without a deploy.
- **As-of date.** Past due and discount deadlines are measured against the
  export date, not today. Otherwise every invoice would look months late.
- **A job is a won opportunity with a project.** The ten open and two lost
  opportunities are copied into our database as raw rows, but they do not
  become jobs and no API endpoint returns them. Pipeline is a separate problem
  and the CRM data is too thin to demo it honestly.
- **One bill can raise several issues.** Each needs a different fix, so each
  is its own issue. Cash totals in `/summary` count every invoice and bill
  once.

## What is not real

| Part | State |
| --- | --- |
| Connectors to live systems | Mocked. One connector reads the export; the pipeline only sees its interface |
| Writing back to source systems | Not built. The app records what people did; it does not send invoices, approve bills or email customers |
| Vendor inbox and documents | Copied as raw rows only; nothing in the API uses them. The export has subjects and file names but no bodies |
| Sign-in | Not built. A "Signed in as" switcher at the top of the sidebar stands in for it, and decides what every page shows |
| Ask | Built. Tests use a stand-in model; real answers need `OPENAI_API_KEY` |
| AI that proposes new issue types, matches vendor emails or drafts follow-ups | Not built |

## Process

Built with Claude Code. The order was: read the briefs and profile the
export; assess the five stakeholders against what the data supports; pick
the Finance and Operations reconciliation problem; write a system design;
mock the UI to settle what the API must return; then build the backend in
six phases, each with tests passing before the next began. The commit history
follows those phases.
