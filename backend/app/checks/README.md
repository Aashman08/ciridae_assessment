# Checks

| File | What it holds |
| --- | --- |
| `checks.toml` | The definitions of the 17 built-in checks |
| `issues.py` | Their logic: step 4 of a sync. Each is one SQL query that returns only its findings |
| `rules.py` | Checks people add as rules: about 80 fields over jobs, invoices, bills, customers and vendors, validated and run as SQL on every sync |
| `reading.py` | Checks people add that only notes can answer. The model reads notes on request; every result must quote them |
| `items.py` | Groups issues into items, the things a person fixes, and the fixed rule for each item's next step |

All three kinds of check run in the same step of a sync and produce issues the same
way. A sync never calls a model.

The built-in checks are defined in [`checks.toml`](checks.toml): one block per check with its
title, description, area, default severity and default tolerance. Each block's logic is the
function of the same name in `issues.py`, marked `@check("<key>")`. The app loads the file at
startup and matches each block to its function. A test fails if a block has no function, a
function has no block, or a block is incomplete.

To add a check: add a block to `checks.toml`, then write its function with `@check("<key>")`.

| Field | Owned by | What happens |
| --- | --- | --- |
| Title, description, area, unit, order | `checks.toml` | Updated from the file on every start and every sync |
| On or off, tolerance, severity | People | Set from the file only for a new database; after that, only the Checks screen or `PATCH /issue-types/{key}` changes them, and each change goes in the audit log |
