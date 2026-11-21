# Reference

The detail behind the [README](../README.md) and the [write-up](../WRITEUP.md): every screen, the sync, the API, and where a model does work.

## Code layout

The backend is in `backend/app/`. Three files sit at the top; the rest is grouped by job.

| Where | What it holds |
| --- | --- |
| `server.py` | Creates the app; registers routes, middleware and error handlers |
| `endpoints.py` | The routes, and nothing else. Each opens a client with `async with` and awaits one method |
| `client.py` | Every operation. Owns the session and the transaction for one request |
| `core/` | Settings and database, models, API contracts, serializers, errors, request IDs |
| `sync/` | The source connector, landing, normalizing and totals, and the schedule |
| `checks/` | The built-in checks, the checks people add (rules and reading), and items |
| `agents/` | Ask, the job review, bill coding, drafts, the note reader and the check writer |

`backend/evals/` scores the agents against the real model. `backend/tests/` holds 157
tests; each run builds its own two databases, so the working ones are never touched.
All database access is async. Schema changes go through Alembic migrations, which
record what has been applied in `recon.alembic_version`.

## The web app

React, TypeScript, Vite and Tailwind, in `frontend/src/`.

| Screen | What it is for |
| --- | --- |
| Ask | Type a question in plain words. The answer comes with the records it rests on and the lookups that produced it. **Ask AI** in the top bar opens the same conversation beside any page, and it knows which job, issue or list is open |
| Overview | Depends on who is signed in. **Finance** sees the ledger: profit, revenue, cost and cash by month, cost by cost code, the contract value split by where the money is, receivables by days late, profit by kind of work, and the lowest-margin jobs. **Operations** (every job) sees what each check found and the jobs to look at first. **An ops manager** sees their own to-do list, each row with a button that starts its next step |
| Jobs | Every job with its revenue, cost, profit and margin. Search by job, number or customer, and sort by any heading. A job's page holds everything about it, including **What needs doing**: the thing to do first, and every item with its next step |
| Job | Revenue and cost figures side by side. Pick one of each and the profit and margin for that pair appear beside them. Under the documents, **Promises and waits from notes** (what the assistant read out of the job's notes, and whether each was kept or missed), then **Notes**: what was written about the job in the project system and on its invoices in accounting, newest first. Actions taken in this app are only in the audit log |
| Issues | One row per job, with tags for what is wrong and the money flagged, counted once. Opening a row lists each thing to fix on that job. Several checks on one invoice or bill are one item with tags. Each item has a button that starts its next step: a drafted message, a suggested job for a bill, an assignment, a date to wait until, or a dismissal. Bills on no job are a group of their own |
| Issue | What is wrong, what to do, the records behind it (an invoice or bill opens its preview in the side pane), plus its history |
| Customer invoices, Vendor bills | Every invoice and bill across jobs |
| Connectors | The three source systems with how much of each was read and when, and the email account a follow-up is sent with |
| Audit log | Every action anyone took in this app, newest first: when, who, the action (Resolved, Assigned, Changed tolerance, Suggested a job…), the record it was done to, and the job. Filter by who, action and job; what syncs did is hidden until switched on. Click an entry to see it in full in the side pane: exactly when, what it changed from and to, the note or reason, and links to the job and the invoice or bill. Notes from the source systems are not here; they are on each job's page |
| Checks (under Settings) | What every sync looks for. Seventeen are built in. **Add a check** takes one description in plain words; the assistant names the check, works out what it looks at, its area and severity, and turns it into a rule over the records (which then runs on every sync as code, with no model) or, when only notes can show it, a reading check. **Try it** shows what it would flag today before it is saved. Every check has an on/off switch, and any with a tolerance can be tuned. **Sync now** in the top bar applies a change straight away |

| Folder | Holds |
| --- | --- |
| `lib/` | `api.ts` (every call to the backend and the shapes it returns), formatting, who is viewing, sync |
| `components/` | The app shell, the shared tables, the side pane and its views, the update dialog and small building blocks |
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
   the source row it came from. Notes written in the project system and on
   invoices in accounting are copied in with their job and invoice.
3. **Total.** Per job: contract, budget, cost three ways, revenue from ledger
   to cash, owed and past due. Stored once per sync so runs can be compared.
4. **Find issues.** Seventeen built-in checks compare the systems, and any checks people added run in the same step. Each finding has a
   stable key, so re-syncing keeps its owner, comments and resolution.

Our tables sit in two schemas of the `harborstone_recon` database. Harborstone's
database is a separate one, and the connection to it is read-only:

| Schema | Tables |
| --- | --- |
| `raw` | `source_record` |
| `recon` | `sync_run`, `company`, `job`, `job_owner`, `cost_code_map`, `money_line`, `job_financials`, `issue_type`, `issue`, `issue_evidence`, `issue_event`, `note`, `note_reading`, `commitment`, `setting_change`, `job_review`, `ask_exchange` |

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
| PATCH | `/issue-types/{key}` | Switch a check off or change its tolerance. Send `actor`; each change is kept in the activity log |
| GET | `/source-records/{id}` | The untouched source row behind any number |
| GET | `/activity` | Notes and actions in one list, newest first. Each entry names its `action`, the `record` it was done to and what it `changes` from and to. Filters: `job`, `owner`, `person`, `source` (project, accounting, app), `kind`, `people_only`; paged |
| GET | `/notes/reading` | How many notes the assistant has not read yet |
| POST | `/notes/read` | Have the assistant read every unread note for promises and waits. A note is read once, and again only if its text changes |
| GET | `/commitments` | Promises and waits read from notes, missed first. Filter by `job`, `owner`, `kind`, `state` (`active`, `missed`, `due_soon`, `open`, `kept`, `done`, `all`) |
| POST | `/checks/draft` | Turn a description into a check and show what it would flag today. Saves nothing |
| POST | `/checks` | Add a check. It runs at once and on every sync after |
| POST | `/checks/read` | Read new or changed notes for every reading check, and refresh what they found |
| POST | `/commitments/{id}/actions` | `done` or `reopen`, with `actor`. Marking one done is kept in the activity log |

## Where a model does work

| Where | What the model does | What stays fixed |
|---|---|---|
| **Ask** (`agents/assistant.py`) | Chooses which fixed lookups to run and writes the answer as text, tables, figures and charts | Every figure comes from a lookup. The page it was asked from only names a job or issue; the tools decide what the person may see |
| **Bill coding** (`agents/coding.py`) | Works out which job an unassigned vendor bill belongs to, from the bill's lines, the email it arrived on, the vendor's history and what each job is spending on. Says how sure it is, and can answer "not a job cost" or "not sure" | It may only name a job it was shown. A low-confidence job is reported as "not sure". A person accepts or rejects; nothing is written to accounting |
| **Job review** (`agents/review.py`) | Reads a job's items with their notes and history and says, for each, act now, wait until a date, or dismiss, and which to do first. This is what a rule cannot do: a note saying payment is promised for Friday means chasing today is wrong | Fixed rules in `checks/items.py` already name the work that fixes each kind of item. The model may only choose among act, wait and dismiss; it cannot dismiss an unpaid invoice or bill, name an item that is not on the job, or set a date in the past. Its review is kept until an item changes. A person confirms every step |
| **Reading notes** (`agents/commitments.py`) | Reads the notes people wrote in the project system and accounting and pulls out every commitment in them: a customer's promise to pay, something promised to a customer, something the work is waiting on, or a next step the team said it would take, each with who, what and the date it resolves to. This is information no check can see; until now it lived in someone's head | It runs only when a person presses **Read new notes**, and never reads a note twice unless its text changed. Each commitment must cite a note it was shown, and a date before the note or more than six months after it is dropped. Whether a commitment was **kept or missed is never the model's call**: code works it out from the records (a payment after the note keeps a payment promise; a date passed with nothing since misses it). A missed payment promise tags its invoice "Payment promised by 31 Jul, not received", and the job review and drafts are given every commitment with its state |
| **Checks people add** (`agents/check_writer.py`, `checks/rules.py`, `checks/reading.py`) | Turns a person's description of a check into a rule over the fields of jobs, customer invoices, vendor bills, customers and vendors (about 80, from figures and dates to people, counts and the words on invoice and bill lines, with the values text fields hold today), once, when the check is written; or, for something only words can show (a dispute, a refusal, a vendor chasing payment), reads the notes, the emails bills came on and what bill lines say | A rule may only name fields from a fixed list per kind of record, and is validated before anyone sees it; then it runs as SQL on every sync like a built-in check. A reading check's findings must quote the notes, and code drops any quote it cannot find. Notes are read only when a person asks, never by a sync. Findings from either kind are issues and items like any other |
| **Follow-up drafts** (`agents/drafts.py`) | Writes the words of a message about an issue | Who it goes to, their address and every fact it may use are chosen by code. Each dollar figure in the draft is checked against those facts. **Send** opens the message in the person's own Gmail, Outlook or mail app for them to send; the app has no mailbox access and sends nothing itself |

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

### How the note reader is tested

`evals/note_reading.py` puts the five notes in the export to the agent and compares what it
finds with commitments written down by hand, matching by note, kind and date:

```
cd backend && uv run python -m evals.note_reading
```

All five notes are dated Friday 24 July, so "Friday" is 31 July and "next week" is Monday
27 July. It reports right, wrong date and missed separately, and counts extras, since a
missed promise matters more than an extra one to glance at. It calls the model once.

The date of the last sync is the clock for all of this: how late something is, whether a
follow-up date has arrived, and what "Friday" in a note means.

## Ask: where AI is used, and where it is not

The figures and the seventeen built-in checks are fixed logic, so the same data always
gives the same answer and every number can be traced. The model never computes
a figure or decides what counts as an issue. This section covers Ask; the table above covers the other places it is used.

It is built on the OpenAI Agents SDK, in `backend/app/agents/assistant.py`.

- **The model cannot query the database.** It can only choose one of ten
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
| `get_issue` | One issue with its evidence and history |
| `totals_by_month` | Customer invoices or vendor bills added up by month, in SQL |

Adding a capability means adding a tool with fixed inputs. There is no tool
that accepts SQL, a table name or a free-form filter.
