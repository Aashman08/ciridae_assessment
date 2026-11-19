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
- `landing.py`, `normalize.py`, `financials.py` and `issues.py` are the four steps
  of a sync, in order.
- `errors.py`, `exception_handlers.py` and `middleware.py` contain application
  errors, HTTP error rendering, request IDs and the optional API key check.

Migrations live in `backend/migrations/` and tests in `backend/tests/`.

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
