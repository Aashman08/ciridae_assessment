# Where AI is used

AI is used in two places: inside the app, where it does work for Harborstone's people,
and in building the app.

## In the app

Six agents, built on the OpenAI Agents SDK. The model is set by `MODEL` in
`backend/.env`. Each agent has fixed inputs and a typed reply, and code checks that
reply before anyone sees it. Details are in [backend/app/agents](backend/app/agents/README.md).

| Agent | What it does | Who it helps | What code still controls |
| --- | --- | --- | --- |
| **Ask** | Answers questions in plain words, with tables and charts | Everyone | It can only call 10 read-only tools. Every dollar figure in an answer is checked against what the tools returned |
| **Job review** | For each open item on a job: act now, wait until a date, or dismiss, and which to do first. Reads notes, so a promised payment means "wait", not "chase" | Tasha, Luis | It cannot dismiss an unpaid invoice or bill, or set a date in the past. A person confirms each step |
| **Bill coding** | Works out which job an unassigned vendor bill belongs to, from its lines, its email and the vendor's history | Rachel | It can only name a job it was shown. A low-confidence guess shows as "not sure". A person accepts or rejects |
| **Follow-up drafts** | Writes the message that fixing an item starts with | Tasha, Rachel | Code picks the recipient and every fact. Each dollar figure is checked. The person sends it from their own mail app |
| **Note reader** | Finds promises and waits in notes: "payment on their next check run", "waiting on the health department" | Everyone | Code, not the model, decides whether a promise was kept or missed. Notes are read only when someone asks |
| **Check writer** | Turns one sentence into a new check: a rule over about 80 fields, or a check that reads notes and emails | Rachel, Luis | The rule is validated before anyone sees it, then runs as plain SQL on every sync. A reading result must quote the text, and code verifies the quote |

### What AI does not do

- Calculate any figure, total, profit or margin.
- Decide what the 17 built-in checks find.
- Run during a sync. Every model call starts with a person.
- Send a message, or change anything in the CRM, project system or accounting.

### How it is tested

- **Tests** (157) do not call OpenAI. They swap the model for a fake one that returns
  answers I wrote in advance, and check that my code handles each answer correctly.
  They test my code, not the model's judgement, so they need no key and cost nothing.
- **Evals** score three agents against answers written by hand, with the real model.
  See [backend/evals](backend/evals/README.md).

| Agent | Last score |
| --- | --- |
| Bill coding | 12 of 15 right, 2 not sure, 1 wrong, none wrong at high confidence |
| Job review | 51 of 54 right; the one real promise in the data read correctly |
| Note reader | 5 of 6 right |

## In building the app

The app was built with Claude Code (Anthropic's Claude) as the coding assistant.

| What | How AI helped |
| --- | --- |
| Understanding the data | Profiled the export: tables, keys, statuses, and where the three systems disagree |
| Backend and web app | Wrote the code, the migrations and the tests to the structure and rules I set in `AGENTS.md` |
| Checking the screens | Took screenshots at phone, laptop and wide-screen sizes, in light and dark mode, after each change |
| Evals | Wrote the eval scripts and ran them against the real model |
| Documents | Drafted the READMEs and the write-up |

The decisions were mine: which problem to solve, for whom, what each screen shows, where
AI is allowed to act and where it is not, and what is mocked. I reviewed each screen as
each person and sent back what did not help them act.
