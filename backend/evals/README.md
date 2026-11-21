# Evals

Scripts that score an agent against answers written by hand, using the real model and
the key in `backend/.env`. They store nothing; the last results are in `*_results.json`.

```bash
cd backend
uv run python -m evals.bill_coding
uv run python -m evals.job_review
uv run python -m evals.note_reading
```

| Script | Last result |
| --- | --- |
| `bill_coding.py` | 12 of 15 right, 2 not sure, 1 wrong, none wrong at high confidence |
| `job_review.py` | 51 of 54 right; the one real promise read correctly |
| `note_reading.py` | 5 of 6 right |

## Bill coding

`evals/bill_coding.py` puts every vendor bill that already has a job to the agent with
that job hidden, and scores the answers against the real ones:

```
cd backend && uv run python -m evals.bill_coding
```

It reports right, wrong and unsure separately, plus the number of wrong answers given
with high confidence, which is the failure that matters. It calls the model once per
bill (15 bills), so it needs `OPENAI_API_KEY`. The agent never sees a bill's own job in
any lookup, which a test asserts, so the score is not leaked. Fifteen bills is a small
set; treat the result as a first check, not a guarantee.

## Job review

`evals/job_review.py` puts every job with something open to the reviewer and compares
each decision with the one a person would make from the same notes:

```
cd backend && uv run python -m evals.job_review
```

The export holds one real promise: a note in accounting on invoice INV-2026-0502, dated
24 July, says payment is on the customer's next check run and to follow up Friday. With
figures as of Tuesday 28 July, the right answer is to wait until Friday 31 July, not to
chase again. The script reports that case on its own, because reading a note is the one
thing the fixed rules cannot do. It calls the model once per job (21 jobs).

## Note reader

`evals/note_reading.py` puts the five notes in the export to the agent and compares what it
finds with commitments written down by hand, matching by note, kind and date:

```
cd backend && uv run python -m evals.note_reading
```

All five notes are dated Friday 24 July, so "Friday" is 31 July and "next week" is Monday
27 July. It reports right, wrong date and missed separately, and counts extras, since a
missed promise matters more than an extra one to glance at. It calls the model once.

The date of the last sync is the clock for all of this: how late something is, whether a
follow-up date has arrived, and what "Friday" in a note means.
