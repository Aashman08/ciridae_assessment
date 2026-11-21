# Harborstone Reconciliation

A reconciliation service for Harborstone, built for the Ciridae case study.

Harborstone runs on a CRM, a project management system and an accounting
system that were never designed as one workflow. This service joins them into one
record per job and reports where they disagree, so that nobody has to
reconcile a job by hand to know whether it is finished and what it earned.
It then helps the right person act: it says what to do first, drafts the message,
reads the notes for promises, and keeps a log of every action.

The repository holds the **backend** (`backend/`), which does the
reconciliation and serves an API, and the **web app** (`frontend/`), which
uses only that API.

- **[WRITEUP.md](WRITEUP.md)** explains what we built, for whom, why, and how we made it.
- **[docs/reference.md](docs/reference.md)** lists every screen, API route and agent in detail.

## Who it is for

- **Rachel Kim, VP of Finance.** Profit and cash figures that tie back to source
  records: revenue, cost and cash by week, cost by cost code, what customers owe.
- **Luis Ortega, VP of Operations.** Every job: urgent starts, jobs that stall,
  spending ahead of schedule, and who owns what.
- **Tasha Green, Project Director.** A short list of what is stuck on her jobs,
  largest first, with a next step she can start from the row.

The "Signed in as" switcher at the top of the sidebar changes between them.

## Run it

Requires Postgres 15+, Python 3.12+, [uv](https://docs.astral.sh/uv/) and Node 20+.

```bash
# 1. Restore Harborstone's export (skip if that database already exists)
createdb harborstone
psql -d harborstone -f source_data.sql

# 2. Start the API. It creates our database and .env if they are missing,
#    applies migrations, and runs the first sync by itself.
cd backend
./run.sh

# 3. In a second terminal, start the web app
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The API docs are at http://localhost:8000/docs.
**Sync now** in the top bar reads the three systems again at any time; otherwise a
sync runs every hour.

If port 8000 is taken, run the API on another port and tell the web app:

```bash
cd backend && uv run uvicorn app.server:app --port 8010
cd frontend && API_URL=http://localhost:8010 npm run dev
```

### Turn on the AI

Put an OpenAI key in `backend/.env`:

```bash
OPENAI_API_KEY=sk-...
MODEL=                # optional; empty uses the OpenAI Agents SDK default
```

Without a key, everything except the AI works, and each AI feature says it is not set up.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+psycopg:///harborstone_recon` | Our own database. Everything this service writes goes here |
| `SOURCE_DATABASE_URL` | `postgresql+psycopg:///harborstone` | Harborstone's export. Opened read-only |
| `SOURCE_SCHEMA` | `source_company` | The schema that holds the export |
| `OPENAI_API_KEY` | not set | Turns on the AI features |
| `MODEL` | not set | The model every agent uses |
| `SYNC_EVERY_MINUTES` | 60 | How often a sync runs. 0 turns the schedule off |
| `API_KEY` | not set | When set, every `/api/v1` request must send it as `X-API-Key` |

## Tests and evals

```bash
cd backend
uv run pytest                          # 157 tests; no key or network needed
uv run python -m evals.bill_coding     # these three call the real model
uv run python -m evals.job_review
uv run python -m evals.note_reading
```

The tests build their own two databases, so the working ones are never touched. The
AI tests use a scripted stand-in for the model. The evals score each agent against
answers written by hand; their last results are in `backend/evals/*_results.json`.
