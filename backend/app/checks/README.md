# Checks

| File | What it holds |
| --- | --- |
| `issues.py` | The 17 built-in checks: step 4 of a sync. Each is one SQL query that returns only its findings |
| `rules.py` | Checks people add as rules: about 80 fields over jobs, invoices, bills, customers and vendors, validated and run as SQL on every sync |
| `reading.py` | Checks people add that only notes can answer. The model reads notes on request; every result must quote them |
| `items.py` | Groups issues into items, the things a person fixes, and the fixed rule for each item's next step |

All three kinds of check run in the same step of a sync and produce issues the same
way. A sync never calls a model.

A built-in check is one function in `issues.py` with its definition in a `@check(...)`
decorator above it. Adding a check means writing one decorated function.

| Field | Owned by | What happens |
| --- | --- | --- |
| Title, description, area, unit, order | Code | Updated from the decorator on every start and every sync |
| On or off, tolerance, severity | People | Set from the decorator only for a new database; after that, only the Checks screen or `PATCH /issue-types/{key}` changes them, and each change goes in the audit log |
