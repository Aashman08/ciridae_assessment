# Harborstone Reconciliation

Joins Harborstone's CRM, project and accounting systems into one record per job, shows
where they disagree, and helps the right person fix it. Built for the Ciridae case study.

## Run it

Needs Postgres 15+, Python 3.12+, [uv](https://docs.astral.sh/uv/) and Node 20+.

```bash
createdb harborstone && psql -d harborstone -f source_data.sql   # once

cd backend && ./run.sh                        # terminal 1: API on :8000
cd frontend && npm install && npm run dev     # terminal 2: app on :5173
```

Open http://localhost:5173. `run.sh` sets up the database and `.env`, asks once for an
OpenAI key (Enter skips; the AI features stay off), and runs the first sync.

## Use it

- **Signed in as** (top of the sidebar) switches between Rachel (finance), Luis
  (operations) and Tasha (project director). Each sees a different first screen.
- **Sync now** (top bar) reads the three systems again. A sync also runs every hour.
- **Ask AI** (top bar) opens the assistant beside any page.

## Read more

- [WRITEUP.md](WRITEUP.md): what I built, for whom, why, and how
- [AI_USED.md](AI_USED.md): where AI is used, in the app and in building it
- [frontend/](frontend/README.md): the screens
- [backend/](backend/README.md): settings, tests and layout
- [backend/app/](backend/app/README.md): the API
- [backend/app/core/](backend/app/core/README.md): database, models, contracts, errors
- [backend/app/sync/](backend/app/sync/README.md): how a sync works
- [backend/app/checks/](backend/app/checks/README.md): the checks and items
- [backend/app/agents/](backend/app/agents/README.md): where a model does work
- [backend/evals/](backend/evals/README.md): agent scores against the real model
