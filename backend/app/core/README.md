# Core

| File | What it holds |
| --- | --- |
| `database.py` | Settings from `.env`, both database engines, the session factory, migrations at startup |
| `models.py` | SQLAlchemy models |
| `schemas.py` | Pydantic request and response contracts |
| `serializers.py` | Models to responses |
| `errors.py`, `exception_handlers.py` | Typed errors, rendered as `{"error": {"type", "message", "request_id"}}` |
| `middleware.py` | Request IDs and the optional API key check |

Our tables sit in two schemas of `harborstone_recon`. Harborstone's database is a
separate one, opened read-only.

| Schema | Tables |
| --- | --- |
| `raw` | `source_record` |
| `recon` | `sync_run`, `company`, `job`, `job_owner`, `cost_code_map`, `money_line`, `job_financials`, `issue_type`, `issue`, `issue_evidence`, `issue_event`, `note`, `note_reading`, `commitment`, `check_reading`, `setting_change`, `job_review`, `ask_exchange` |

All database access is async. Schema changes go through Alembic migrations, recorded in
`recon.alembic_version`. Money is `Decimal`, sent as a decimal string.
