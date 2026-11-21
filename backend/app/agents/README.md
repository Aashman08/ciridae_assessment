# Agents

Every place a model does work. Each is one agent with fixed inputs and a typed reply
that code checks before it is used. Tests use a scripted stand-in for the model.

| Where | What the model does | What stays fixed |
|---|---|---|
| **Ask** (`assistant.py`) | Chooses which fixed lookups to run and writes the answer as text, tables, figures and charts | Every figure comes from a lookup. The page it was asked from only names a job or issue; the tools decide what the person may see |
| **Bill coding** (`coding.py`) | Works out which job an unassigned vendor bill belongs to, from the bill's lines, the email it arrived on, the vendor's history and what each job is spending on. Says how sure it is, and can answer "not a job cost" or "not sure" | It may only name a job it was shown. A low-confidence job is reported as "not sure". A person accepts or rejects; nothing is written to accounting |
| **Job review** (`review.py`) | Reads a job's items with their notes and history and says, for each, act now, wait until a date, or dismiss, and which to do first. This is what a rule cannot do: a note saying payment is promised for Friday means chasing today is wrong | Fixed rules in `../checks/items.py` already name the work that fixes each kind of item. The model may only choose among act, wait and dismiss; it cannot dismiss an unpaid invoice or bill, name an item that is not on the job, or set a date in the past. Its review is kept until an item changes. A person confirms every step |
| **Reading notes** (`commitments.py`) | Reads the notes people wrote in the project system and accounting and pulls out every commitment in them: a customer's promise to pay, something promised to a customer, something the work is waiting on, or a next step the team said it would take, each with who, what and the date it resolves to. This is information no check can see; until now it lived in someone's head | It runs only when a person presses **Read new notes**, and never reads a note twice unless its text changed. Each commitment must cite a note it was shown, and a date before the note or more than six months after it is dropped. Whether a commitment was **kept or missed is never the model's call**: code works it out from the records (a payment after the note keeps a payment promise; a date passed with nothing since misses it). A missed payment promise tags its invoice "Payment promised by 31 Jul, not received", and the job review and drafts are given every commitment with its state |
| **Checks people add** (`check_writer.py`, `../checks/rules.py`, `../checks/reading.py`) | Turns a person's description of a check into a rule over the fields of jobs, customer invoices, vendor bills, customers and vendors (about 80, from figures and dates to people, counts and the words on invoice and bill lines, with the values text fields hold today), once, when the check is written; or, for something only words can show (a dispute, a refusal, a vendor chasing payment), reads the notes, the emails bills came on and what bill lines say | A rule may only name fields from a fixed list per kind of record, and is validated before anyone sees it; then it runs as SQL on every sync like a built-in check. A reading check's findings must quote the notes, and code drops any quote it cannot find. Notes are read only when a person asks, never by a sync. Findings from either kind are issues and items like any other |
| **Follow-up drafts** (`drafts.py`) | Writes the words of a message about an issue | Who it goes to, their address and every fact it may use are chosen by code. Each dollar figure in the draft is checked against those facts. **Send** opens the message in the person's own Gmail, Outlook or mail app for them to send; the app has no mailbox access and sends nothing itself |

## Ask

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
