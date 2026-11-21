# Web app

React, TypeScript, Vite and Tailwind. It uses only the backend API.

```bash
npm install
npm run dev      # http://localhost:5173; passes /api to API_URL (default http://localhost:8000)
npm run build    # type-check and build
npm run lint     # keep it at zero warnings
```

## Screens

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

## Code

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
