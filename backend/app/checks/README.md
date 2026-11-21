# Checks

| File | What it holds |
| --- | --- |
| `issues.py` | The 17 built-in checks: step 4 of a sync. Each is one SQL query that returns only its findings |
| `rules.py` | Checks people add as rules: about 80 fields over jobs, invoices, bills, customers and vendors, validated and run as SQL on every sync |
| `reading.py` | Checks people add that only notes can answer. The model reads notes on request; every result must quote them |
| `items.py` | Groups issues into items, the things a person fixes, and the fixed rule for each item's next step |

All three kinds of check run in the same step of a sync and produce issues the same
way. A sync never calls a model. Tolerances and on/off switches are data in
`issue_type`, changed on the Checks screen or through `PATCH /issue-types/{key}`.
