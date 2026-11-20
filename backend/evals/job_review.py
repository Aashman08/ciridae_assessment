"""Score the job reviewer against answers decided by hand.

Every job with something open is put to the agent, and its decision for each
item is compared with the one a person would make from the same notes. This
calls the model once per job, so it needs OPENAI_API_KEY in backend/.env.

    cd backend && uv run python -m evals.job_review

What a right answer is:
- An unpaid or unsent invoice, or an unpaid bill, with no promise pending: act.
- An item with a note promising something on a date that has not yet passed: wait,
  until that date.
- A cost or billing gap: act, or dismiss if it is small. Either is defensible, so
  only "wait" is counted wrong there, since nothing is pending.

The one place the export holds a promise is invoice INV-2026-0502: a note dated
24 July says payment is on the customer's next check run and to follow up Friday.
With the figures as of Tuesday 28 July, the right answer is to wait until Friday
31 July, not to chase again. A reviewer that says "act" there has not read the note.
That is a small test of the thing the agent exists for, and is reported on its own.
"""

import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from app import review
from app.client import ITEM_PARTS, create_recon_client
from app.items import fingerprint
from app.models import Issue, Job

RESULTS = Path(__file__).parent / "job_review_results.json"

# Where a person, reading the notes, would not simply act. Everything else: see `expected`.
BY_HAND = {
    "invoice_unpaid:INV-2026-0502": ("wait", "2026-07-31"),
}
GAPS = ("cost_gap", "billing_gap")


def expected(key: str, kind: str) -> tuple[set[str], str | None]:
    """The decisions that count as right for an item, and the date when it is a wait."""
    if key in BY_HAND:
        decision, until = BY_HAND[key]
        return {decision}, until
    return ({"act", "dismiss"}, None) if kind in GAPS else ({"act"}, None)


def verdict(decision: str, until: str | None, key: str, kind: str) -> str:
    right, on = expected(key, kind)
    if decision not in right:
        return "wrong"
    return "right" if on is None or until == on else "wrong date"


def summary(rows: list[dict]) -> dict:
    counts = {outcome: sum(row["verdict"] == outcome for row in rows) for outcome in ("right", "wrong", "wrong date")}
    read = [row for row in rows if row["item"] in BY_HAND]
    return {
        "items": len(rows),
        **counts,
        "accuracy": round(counts["right"] / len(rows), 3) if rows else None,
        "notes_read_correctly": f"{sum(row['verdict'] == 'right' for row in read)} of {len(read)}",
    }


async def main() -> None:
    rows: list[dict] = []
    async with create_recon_client("eval-job-review") as client:
        run = await client._current_run()
        jobs = list(await client.db.scalars(select(Job).order_by(Job.job_number)))
        for job in jobs:
            issues = list(
                await client.db.scalars(
                    select(Issue).where(Issue.job_id == job.id, Issue.status.in_(("open", "assigned"))).options(*ITEM_PARTS)
                )
            )
            if not issues:
                continue
            items = await client._items_from(issues, run.as_of)
            about = {"name": job.name, "stage": job.stage, "project_notes": await client._project_notes(job)}
            # Asked directly, so nothing is stored: a run of this script does not change what the app shows.
            answer = await client._with_model(review.review(about, items, run.as_of))
            assert fingerprint(items)  # the same items the app would review
            for item in items:
                entry = answer["items"].get(item.key, {"decision": "act", "until": None, "reason": "(not mentioned)"})
                row = {
                    "job": job.job_number, "item": item.key, "decision": entry["decision"], "until": entry["until"],
                    "verdict": verdict(entry["decision"], entry["until"], item.key, item.kind),
                    "first": answer["first"] == item.key, "reason": entry["reason"],
                }
                rows.append(row)
                print(f"{row['verdict']:10} {row['item']:34} {row['decision']:8} {row['until'] or '':10} {row['reason'][:70]}")

    result = {"summary": summary(rows), "items": rows}
    RESULTS.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["summary"], indent=2))
    print(f"Written to {RESULTS}")


if __name__ == "__main__":
    asyncio.run(main())
