# Backend

FastAPI, async SQLAlchemy 2 and PostgreSQL, run with [uv](https://docs.astral.sh/uv/).

```bash
./run.sh                 # create the database and .env if missing, then start the API on :8000
uv run pytest            # 157 tests; no key or network needed
uv run alembic revision --autogenerate -m "..."   # after a change to app/core/models.py
```

Startup applies pending migrations and, if no sync has ever run, runs the first one.

## Where things are

| Folder | What it holds | Read more |
| --- | --- | --- |
| `app/` | `server.py`, `endpoints.py` (the API) and `client.py` (every operation) | [app/README.md](app/README.md) |
| `app/core/` | Settings, database, models, API contracts, errors | [app/core/README.md](app/core/README.md) |
| `app/sync/` | Reading the source systems into the app's database | [app/sync/README.md](app/sync/README.md) |
| `app/checks/` | What is wrong: built-in checks, checks people add, items | [app/checks/README.md](app/checks/README.md) |
| `app/agents/` | Every place a model does work | [app/agents/README.md](app/agents/README.md) |
| `evals/` | Scores for the agents against the real model | [evals/README.md](evals/README.md) |
| `migrations/` | Alembic migrations | |
| `tests/` | Tests; each run builds its own two databases | |

## Settings

Read from `backend/.env`, which `run.sh` copies from `.env.example`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+psycopg:///harborstone_recon` | The app's own database. Everything this service writes goes here |
| `SOURCE_DATABASE_URL` | `postgresql+psycopg:///harborstone` | Harborstone's export. Opened read-only |
| `SOURCE_SCHEMA` | `source_company` | The schema that holds the export |
| `OPENAI_API_KEY` | not set | Turns on the AI features. `run.sh` asks for it once |
| `MODEL` | not set | The model every agent uses. Empty uses the OpenAI Agents SDK default |
| `SYNC_EVERY_MINUTES` | 60 | How often a sync runs. 0 turns the schedule off |
| `API_KEY` | not set | When set, every `/api/v1` request must send it as `X-API-Key` |
