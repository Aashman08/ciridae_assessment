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

- **Rachel Kim, VP of Finance.** She needs profit and cash figures that tie back
  to source records. Her first screen is the ledger: revenue, cost and cash by
  month, cost by cost code, receivables by days late.
- **Tasha Green, Project Director.** Her team does the follow-ups. She needs
  a short list of what is stuck on her jobs, largest first, with a next step
  she can start from the row.
- **Luis Ortega, VP of Operations.** He sees every job: what each check found
  and which jobs to look at first.

All three read the same data. What differs is the first screen and, for Tasha,
that every page is limited to her own jobs.

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
after that it syncs on a schedule (`SYNC_EVERY_MINUTES`, every hour unless set). Interactive API docs are at
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
| `ASK_MODEL` | not set | Model for Ask, follow-up drafts and bill coding. Empty uses the OpenAI Agents SDK default |
| `SYNC_EVERY_MINUTES` | 60 | How often the source systems are read. 0 turns the schedule off |

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
| Ask | Type a question in plain words. The answer comes with the records it rests on and the lookups that produced it. **Ask AI** in the top bar opens the same conversation beside any page, and it knows which job, issue or list is open |
| Overview | Depends on who is signed in. **Finance** sees the ledger: profit, revenue, cost and cash by month, cost by cost code, the contract value split by where the money is, receivables by days late, profit by kind of work, and the lowest-margin jobs. **Operations** (every job) sees what each check found and the jobs to look at first. **An ops manager** sees their own to-do list, each row with a button that starts its next step |
| Jobs | Every job with its revenue, cost, profit and margin. Search by job, number or customer, and sort by any heading. A job's page holds everything about it, including **What needs doing**: the thing to do first, and every item with its next step |
| Job | Revenue and cost figures side by side. Pick one of each and the profit and margin for that pair appear beside them |
| Issues | One row per job, with tags for what is wrong and the money flagged, counted once. Opening a row lists each thing to fix on that job. Several checks on one invoice or bill are one item with tags. Each item has a button that starts its next step: a drafted message, a suggested job for a bill, an assignment, a date to wait until, or a dismissal. Bills on no job are a group of their own |
| Issue | What is wrong, what to do, the records behind it and the untouched source row for each, plus its history |
| Customer invoices, Vendor bills | Every invoice and bill across jobs |
| Connectors | The three source systems with how much of each was read and when, and the email account a follow-up is sent with |
| Issue types | The thirteen checks, with an on/off switch and tolerance for each. **Sync now** here applies a change straight away |

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
| GET | `/summary` | Cash position, contract-to-cash totals, issues by type, and `flagged_documents`: the invoices and bills with an open issue, each counted once. `owner` filters to one ops manager |
| GET | `/jobs` | Jobs with figures from each system, including `ledger_profit` and `ledger_margin_pct`. Filter by `stage`, `owner`, `branch`, `has_issues`; search with `q`; order with `sort` and `order` |
| GET | `/jobs/{number}` | One job: revenue and cost figures side by side, and profit for the `revenue` and `cost` pair chosen |
| GET | `/jobs/{number}/lines` | Every money line on the job |
| GET | `/lines?kind=` | Invoices or vendor bills across jobs. Filter with `status`, `no_job` and `balance` (`open` or `past_due`) |
| GET | `/issues` | The work queue, largest first. Filter by `type`, `owner`, `status`, `severity`, `job`; order with `sort` (`amount`, `severity`, `due`, `follow_up`, `owner`) and `order`. Each issue says why its owner has it (`owner_role`), how late it is (`days_late`) and how many other issues are about the same document (`same_document`) |
| GET | `/issues/{id}` | One issue with its evidence and history |
| GET | `/items` | What needs fixing, grouped by job: one item per invoice, bill or gap, with tags, its next step and its history. Filter by `state`, `owner`, `type` |
| POST | `/items/{key}/actions` | `update`, `resolve`, `dismiss` or `reopen` an item. It applies to every check behind it |
| POST | `/items/{key}/draft` | Draft the message that fixing an item starts with |
| POST | `/jobs/{number}/review` | Have the assistant review a job's items |
| POST | `/issues/{id}/draft` | Draft a follow-up message for a person to send themselves. Returns the recipient, subject, body and anything to check |
| POST | `/issues/{id}/coding` | Suggest which job an unassigned vendor bill belongs to, with confidence and reasons |
| POST | `/issues/{id}/actions` | `update` saves any of a note, a new owner and a follow-up date together; `resolve` and `reopen` change its status |
| GET | `/people` | Who an issue can be assigned to |
| GET | `/finance` | The ledger's view: revenue, cost, invoiced and collected by month and by week, each with running totals to date; cost by cost code with each code's share and the total logged; receivables by days late, profit by kind of work |
| GET | `/sources` | The three source systems: tables and records held, and when last read |
| GET | `/customer-balances` | What each customer owes, largest first |
| POST | `/ask` | Ask a question in plain words. Returns the answer as plain text (`answer`) and laid out for display (`spec`), the lookups used and the records it rests on, and saves the exchange |
| GET, DELETE | `/ask/history?asked_by=` | Read or clear one person's saved conversation |
| GET | `/issue-types` | The checks, their settings and what each has found |
| PATCH | `/issue-types/{key}` | Switch a check off or change its tolerance |
| GET | `/source-records/{id}` | The untouched source row behind any number |

## Four places the model does work

| Where | What the model does | What stays fixed |
|---|---|---|
| **Ask** (`assistant.py`) | Chooses which fixed lookups to run and writes the answer as text, tables, figures and charts | Every figure comes from a lookup. The page it was asked from only names a job or issue; the tools decide what the person may see |
| **Bill coding** (`coding.py`) | Works out which job an unassigned vendor bill belongs to, from the bill's lines, the email it arrived on, the vendor's history and what each job is spending on. Says how sure it is, and can answer "not a job cost" or "not sure" | It may only name a job it was shown. A low-confidence job is reported as "not sure". A person accepts or rejects; nothing is written to accounting |
| **Job review** (`review.py`) | Reads a job's items with their notes and history and says, for each, act now, wait until a date, or dismiss, and which to do first. This is what a rule cannot do: a note saying payment is promised for Friday means chasing today is wrong | Fixed rules in `items.py` already name the work that fixes each kind of item. The model may only choose among act, wait and dismiss; it cannot dismiss an unpaid invoice or bill, name an item that is not on the job, or set a date in the past. Its review is kept until an item changes. A person confirms every step |
| **Follow-up drafts** (`drafts.py`) | Writes the words of a message about an issue | Who it goes to, their address and every fact it may use are chosen by code. Each dollar figure in the draft is checked against those facts. **Send** opens the message in the person's own Gmail, Outlook or mail app for them to send; the app has no mailbox access and sends nothing itself |

### How the bill coder is tested

`evals/bill_coding.py` puts every vendor bill that already has a job to the agent with
that job hidden, and scores the answers against the real ones:

```
cd backend && uv run python -m evals.bill_coding
```

It reports right, wrong and unsure separately, plus the number of wrong answers given
with high confidence, which is the failure that matters. It calls the model once per
bill (15 bills), so it needs `OPENAI_API_KEY`. The agent never sees a bill's own job in
any lookup, which a test asserts, so the score is not leaked. Fifteen bills is a small
set; treat the result as a first check, not a guarantee.

### How the job review is tested

`evals/job_review.py` puts every job with something open to the reviewer and compares
each decision with the one a person would make from the same notes:

```
cd backend && uv run python -m evals.job_review
```

The export holds one real promise: a note in accounting on invoice INV-2026-0502, dated
24 July, says payment is on the customer's next check run and to follow up Friday. With
figures as of Tuesday 28 July, the right answer is to wait until Friday 31 July, not to
chase again. The script reports that case on its own, because reading a note is the one
thing the fixed rules cannot do. It calls the model once per job (21 jobs).

The date of the last sync is the clock for all of this: how late something is, whether a
follow-up date has arrived, and what "Friday" in a note means.

## Ask: where AI is used, and where it is not

The figures and the thirteen checks are fixed logic, so the same data always
gives the same answer and every number can be traced. The model never computes
a figure or decides what counts as an issue. This section covers Ask; the table
above covers the other two places it is used.

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
