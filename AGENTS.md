# Repository Guidelines

## Project Structure & Module Organization

The backend is a Python API using FastAPI, async SQLAlchemy 2 and PostgreSQL.
Source lives in `backend/app/`:

- `server.py` creates the FastAPI application and registers middleware, routes
  and exception handlers.
- `endpoints.py` contains HTTP route definitions and nothing else. Every route
  opens a client with `async with` and awaits one method on it.
- `client.py` contains every operation: running a sync, reading jobs and issues,
  acting on issues. It owns the session and the transaction for one request.
- `database.py` loads settings, creates both engines and the session factory, and
  applies migrations at startup.
- `models.py` contains SQLAlchemy persistence models.
- `schemas.py` contains Pydantic request and response contracts.
- `serializers.py` converts database models into API response models.
- `connector.py` reads rows from the source systems.
- `assistant.py` is Ask: the agent, its instructions and its fixed tools.
- `landing.py`, `normalize.py`, `financials.py` and `issues.py` are the four steps
  of a sync, in order.
- `errors.py`, `exception_handlers.py` and `middleware.py` contain application
  errors, HTTP error rendering, request IDs and the optional API key check.

Migrations live in `backend/migrations/` and tests in `backend/tests/`.

The web app is React, TypeScript, Vite and Tailwind, in `frontend/src/`:

- `lib/api.ts` holds every call to the backend and the shapes it returns. Nothing
  else calls `fetch`.
- `lib/` also holds formatting, the current viewer and sync helpers.
- `components/` holds the shell, the shared job and issue tables, the resolve
  dialog and small building blocks in `ui.tsx`.
- `pages/` holds one file per screen.
- `index.css` holds the design tokens and the one shared table style.

## Build, Test, and Development Commands

Run commands from `backend/`:

- `./run.sh`: create the database and `.env` if missing, then start the API.
- `uv sync`: create or synchronize the environment.
- `uv run uvicorn app.server:app --reload`: run the API.
- `uv run pytest -v`: run the complete test suite.
- `uv run alembic revision --autogenerate -m "..."`: create a migration after
  changing `models.py`.

Interactive API documentation is at `http://localhost:8000/docs`. Application
startup applies any pending migrations.

## Frontend Commands

Run from `frontend/`:

- `npm run dev`: start the web app on port 5173. It passes `/api` to the backend
  at `API_URL`, which defaults to `http://localhost:8000`.
- `npm run build`: type-check and build.
- `npm run lint`: lint. Keep it at zero warnings.

## Frontend Conventions

- Colours, fonts and shadows come from the tokens in `index.css`. Do not write a
  hex colour in a component.
- Sizes are written in rem, never px, so the whole interface scales from one
  value: `html { font-size }` in `index.css`, currently 112.5%. Only hairlines
  under 4px (borders, rings, outlines) stay in px.
- Every size and gap is a multiple of 4px at the default scale (0.25rem). One accent colour, used only for what
  needs a person. Charts are the one other place with colour: `--series-1` to
  `--series-3`, always in that order, drawn by `components/Chart.tsx`. One icon set (lucide) at 16px with a 1.5 stroke.
- Sentence case everywhere, weights 400 to 600, no uppercase labels, no emoji.
- Money is formatted by `money()` in `lib/format.ts` and nowhere else. Figures
  use the mono face; words do not.
- Profit, margin and totals are computed by the backend. The frontend never
  re-derives them.
- Filters and paging go in the URL search parameters.
- A page is one column of full-width blocks that share the same left and right
  edge. Do not hang a narrow panel off the side of a wider one; it leaves the
  page lopsided. Lists are tables, styled like every other table.
- In a table, one fact per column and one line per row. Do not stack two facts in
  a cell (a name over its ID, a title over its detail), and do not join them in
  a sentence either ("INV-2026-0538, 14 days past due"). If the API only has the
  sentence, add the separate fields to the API.
- A row that leads somewhere is clickable across its whole width, with a pointer
  cursor. A button inside it stops the click from also opening the row.
- The Ask screen is a chat and follows chat conventions: the person's message in a
  bubble on the right, the reply on the left, the input pinned at the bottom, a
  spinner while it works, and sources as a vertical list in a panel beside the
  conversation. It is the one screen with a reading-width column and a side panel.
- Content fills the window. Do not cap the page width; a cap leaves a dead band on
  wide monitors.
- After changing a screen, open it in a browser at phone width, at 1440 and at
  2000 wide, and in dark mode before calling it done.

## Coding Style & Naming Conventions

Use four-space indentation, type hints, `snake_case` functions and modules,
`PascalCase` classes and uppercase constants. Keep route functions thin and keep
business and database operations in `client.py`.

Filter, sort, page and total in SQL. Python should only receive the rows it is
going to return; never load a whole table and trim it in a loop.

All database access is async. Relationships are declared `lazy="raise"`, so every
query must name what it loads with `selectinload`.

Represent money with `Decimal` and serialize it as a decimal string. Keep profit
and margin formulas in `financials.py`; do not repeat them in routes or schemas.

## Ask and AI

Figures, totals and issue detection are fixed logic and must stay that way. The
model in `assistant.py` only answers questions, through tools.

- A tool is a typed, read-only call to one `ReconClient` method. Never add a tool
  that takes SQL, a table name or a free-form filter.
- Apply the viewer's scope (`owner`) inside the tool, from the context, never from
  a model-supplied input.
- Tools return JSON strings, not Python objects.
- The reply is typed as well: `AskReply` in `schemas.py`, a list of text, table,
  figures and chart blocks. The API returns it as a json-render spec and
  `components/AnswerView.tsx` draws it. To add a kind of block, add it in all
  three places (the schema, `answer_spec` in `serializers.py`, the catalog); never
  let the model send markup or free-form layout.
- Test with the scripted stand-in model in `tests/test_07_ask.py`. Tests must not
  need an API key or the network.

## Two Databases

`DATABASE_URL` is ours and takes every write. `SOURCE_DATABASE_URL` is
Harborstone's and is opened read-only. Never write to the source, and never put
our tables in it.

## Schema Changes

Every schema change goes through an Alembic migration generated from
`models.py`. Alembic records applied revisions in `recon.alembic_version`. Do not
create or alter our tables by hand.

## Testing Guidelines

Use pytest with `test_*.py` files and the fixtures in `tests/conftest.py`. Tests
are async and share one event loop. Each test module starts with our tables
empty; request the `synced` fixture when a module needs one sync of the export.
Use `recon` to call client operations, `api` for HTTP, `db` for direct assertions
and `source` to change the test copy of the export.

Tests build `harborstone_test` and `harborstone_recon_test`. They never touch the
working databases.

## Commit Guidelines

Use short, imperative commit subjects such as `Add issue type tolerance check`.
Update the README when API contracts change.
