# Harborstone Reconciliation: Write-up

This document tells what I built for Harborstone, for whom, and why. It also tells
how I made the decisions and how I did the work. It uses the rules of ASD-STE100
Simplified Technical English: short sentences, active voice, and one word for one
thing. For each screen, API route and agent, refer to the README in its folder.

## 1. Summary

Harborstone uses three systems: a CRM, a project system and an accounting system.
The three systems do not agree about a job. People find the differences by hand,
with exports and spreadsheets.

I built one service that reads the three systems. It joins them into one record
for each job. It finds where the systems do not agree, and it tells the correct person
what to do next. AI agents help the person act. Fixed code calculates every figure
and decides what is wrong.

## 2. The problem in the data

I read the export before I chose what to build. The data on 28 July 2026 shows
these facts:

| What I found | Amount |
| --- | --- |
| Customers owe Harborstone | $1,477,564 |
| Of that, past its due date | $719,004 |
| Invoices approved or in draft, but not sent | $369,100 (5 invoices) |
| Revenue booked but not invoiced | $127,600 (2 jobs) |
| Vendor bills not paid and not in the ledger | $423,215 (18 bills) |
| Jobs where project cost and ledger cost disagree by more than 2% | 17 of 25 jobs |
| Jobs with no operations manager | 7 jobs |

The 17 built-in checks find 65 problems on 25 jobs. Many problems are about the same
invoice or bill. The app groups them into 55 items, the things a person must fix.

Each item is money that is late, money that is not billed, or a figure that nobody
can trust. This work gives a fast return. It also gives the clean data that every
next step needs.

## 3. Who it is for

I designed the app for the three people in the company brief. Each person sees a
different first screen. The "Signed in as" switcher changes between them.

| Person | Decision or work | What the app gives |
| --- | --- | --- |
| Rachel Kim, VP of Finance | Which figures can I trust? Where is cash stuck? | The ledger view: profit, revenue, cost and cash by week; cost by cost code; what customers owe and how late it is; where each dollar of the contract is now |
| Luis Ortega, VP of Operations | Which jobs need me? Who owns what? | Urgent starts measured from the date of the damage, jobs that stall, spending ahead of schedule, and the work for each owner |
| Tasha Green, Project Director | What do I do today? | Her list of items, largest first. Each row has a button that starts the next step |

## 4. What I built

### 4.1 One record for each job

A sync reads the three systems and does four steps:

1. Copy each source row into the app's database, with a hash of its content.
2. Join each project to its opportunity, customer, budget and owners. The result is one job.
3. Calculate the totals for each job: contract, budget, three cost figures, revenue, cash.
4. Run the checks. Each result becomes an issue with a stable key.

Every figure keeps a link to the source row that it came from. A sync never writes
to the source systems. The connection to Harborstone's database is read-only.

### 4.2 No silent choice of cost

The project system and the ledger give different costs for most jobs. Nothing in the
data links a cost entry to a bill. Thus I do not choose one figure. The job page
shows each revenue figure and each cost figure. The person selects a pair, and the
app calculates profit for that pair. A warning icon shows when two systems disagree.

### 4.3 Items and next steps

The app groups issues into items. One unpaid invoice with three problems is one item
with three tags. Fixed rules give each kind of item its next step:

- **Chase the customer** for an unpaid invoice.
- **Get the invoice sent** for an invoice that is not sent.
- **Suggest a job** for a bill that has no job.
- **Ask to reconcile costs** when cost figures disagree.

A person can also assign the item, set a follow-up date, log an update, resolve it,
or dismiss it as expected. The app never changes the source systems.

### 4.4 The audit log

The audit log records each action that a person, a sync or an AI agent does. Each
entry shows when, who, the action, and the record. Click an entry to see all of it.
The side pane shows what changed from and to, the note, and links to the job and the document.

### 4.5 Checks that people add

A person writes a new check in one sentence. For example: "Sent invoices with more
than $100,000 still open." The AI agent does these things one time:

1. It gives the check a name, an area and a severity.
2. It writes a rule over a fixed list of about 80 fields.
3. Code validates the rule.
4. The app shows what the rule finds today, before the person saves it.

After that, the rule runs on each sync as code, like the built-in checks. No model
runs during a sync. Some things only words can show, for example a customer dispute.
For those, the AI agent reads the notes and emails. Each result must quote the text.

## 5. Where AI helps, and how I control it

Figures, totals and the built-in checks are fixed code. The same data always gives
the same result, and you can trace each figure. AI agents do the work that rules
cannot do: they read words and they write words.

| Agent | What it does | The control |
| --- | --- | --- |
| Ask | Answers a question in plain words, with tables and charts | It can only call 10 fixed, read-only tools. Code checks each dollar figure in the answer against the tool results |
| Job review | For each item: act now, wait until a date, or dismiss. It also selects the first item | It cannot dismiss an unpaid invoice or bill, or set a date in the past |
| Bill coding | Finds the job for a bill that has no job | It can only name a job that it was shown. A guess with low confidence shows as "not sure" |
| Drafts | Writes a follow-up message | Code selects the recipient and every fact. Code checks each dollar figure. The person sends the message |
| Note reader | Finds promises and waits in notes | Code, not the model, decides if a promise was kept or missed |
| Check writer | Turns a sentence into a check | Code validates the rule before a person sees it |

Each agent has a typed reply. Code checks the reply before the app uses it. A person
confirms each step. The tests do not call the model. A fake model gives answers that
I wrote, and the tests check that my code handles each answer correctly.

### 5.1 Results against the real model

I scored three agents against answers that I wrote by hand:

| Agent | Result |
| --- | --- |
| Bill coding | 12 of 15 correct, 2 "not sure", 1 wrong. No wrong answer had high confidence |
| Job review | 51 of 54 decisions correct. It read the one real promise correctly: wait until 31 July |
| Note reader | 5 of 6 commitments correct. It did not find "weekly photo updates" |

The job review also found a weak point in my own checks. It dismissed "no operations
manager" on a cancelled job and on a closed job. That check must not flag those jobs.

## 6. Design decisions

- **A separate database.** The joined records, issues and history have no place in the
  three systems. I keep them in a separate database.
- **The date of the export is the clock.** The app measures "late" against the sync
  date, not today. Otherwise every invoice looks months late.
- **A job is a won opportunity with a project.** The 10 open and 2 lost opportunities
  stay as raw rows. The CRM data is too thin to show a sales pipeline honestly.
- **Filters, totals and pages are calculated in SQL.** Python only gets the rows it shows.
- **A sync never calls a model.** AI work runs only when a person asks for it.
- **Notes and actions stay separate.** Notes from the source systems show on the job
  page. Actions in this app show only in the audit log.

## 7. What is real and what is mocked

| Part | State |
| --- | --- |
| Sync from the export, checks, items, audit log | Real |
| AI agents | Real. They need `OPENAI_API_KEY` |
| Connectors to live systems | Mocked. One connector reads the export. The rest of the app sees only its interface |
| Write-back to the source systems | Not built. The app records what people did. It does not send invoices or approve bills |
| Email | The app does not send email. "Send" opens the draft in the person's own mail app |
| Sign-in | Not built. The "Signed in as" switcher stands in for it |

## 8. How I did the work

I used Claude Code for the work. I did these steps in this order:

1. Read the brief and the case study.
2. Profile the export: tables, keys, statuses, and where the systems disagree.
3. Compare each person's needs with what the data can support.
4. Select the problem: one trusted record for each job, and the work to fix it.
5. Write a system design, then a UI mock, to settle what the API must return.
6. Build the backend in phases. Make all tests pass before the next phase.
7. Build the web app on the API.
8. Review each screen as each person. Remove what did not help them act.
9. Add AI only where it removes work that rules cannot remove.
10. Score each agent against the real model.

The backend has four packages: `core`, `sync`, `checks` and `agents`. Three files sit
above them: `server.py`, `endpoints.py` and `client.py`. Each route calls one method
on the client. The client owns the session and the transaction for the request.

## 9. What I would build next

To help Harborstone grow 5 times, the next steps are:

1. **Live connectors** to the CRM, the project system and accounting, with write-back
   after a person approves. For example, send an invoice or approve a bill from the item.
2. **Fix the "no operations manager" check** so it does not flag closed or cancelled jobs.
3. **Month-end close** for finance: what blocks the close, and what is not booked.
4. **A view for each branch**, with the same figures and items.
5. **Sales pipeline** when the CRM data is complete enough to trust.
6. **Sign-in and roles**, to replace the "Signed in as" switcher.
7. **More data for the AI**, such as the full text of vendor emails and attachments.
