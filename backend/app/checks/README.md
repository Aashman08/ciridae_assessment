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

Every check is a row in the `issue_type` table. The database owns it, and people change it
on the Checks screen (or `PATCH /issue-types/{key}`):

- **Edit** a check's name, description, severity or tolerance, or switch it on or off.
- **Add** a check in one sentence. The check writer turns it into a rule or a reading
  check, and saving it creates a new row.

Each change goes in the audit log.

[`checks.toml`](checks.toml) only seeds a new database with the 17 built-in checks. At
startup the app inserts a built-in check that is missing and never overwrites a row that
exists, so an edit made on the Checks screen stays. Each built-in check's logic is the
function of the same name in `issues.py`, marked `@check("<key>")`. A test fails if a block
has no function, a function has no block, or a block is incomplete.
