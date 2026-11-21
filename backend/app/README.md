# API

`server.py` creates the app. `endpoints.py` holds the routes and nothing else: each
opens a client with `async with` and awaits one method on it. `client.py` holds every
operation and owns the session and transaction for one request.

Interactive docs: http://localhost:8000/docs

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
