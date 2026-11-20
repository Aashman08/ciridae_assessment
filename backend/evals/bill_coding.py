"""Score the bill coder against bills whose job is already known.

Every vendor bill in the export that is coded to a job is put to the agent with
that job hidden. Its answer is compared with the real one. This calls the model
once per bill, so it needs OPENAI_API_KEY in backend/.env and costs a little.

    cd backend && uv run python -m evals.bill_coding

A right answer is the right job. "Unsure" is not counted as right or wrong: it
is the agent declining to guess, which is what we want when the evidence is thin.
A wrong job stated with high confidence is the failure that matters most.
"""

import asyncio
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.client import create_recon_client
from app.models import MoneyLine

RESULTS = Path(__file__).parent / "bill_coding_results.json"


def verdict(decision: str, suggested: str | None, actual: str | None) -> str:
    """right, wrong or unsure, for a bill whose real job (or lack of one) is known."""
    if decision == "unsure":
        return "unsure"
    if actual is None:
        return "right" if decision == "not_a_job_cost" else "wrong"
    return "right" if decision == "job" and suggested == actual else "wrong"


def summary(rows: list[dict]) -> dict:
    counts = {outcome: sum(row["verdict"] == outcome for row in rows) for outcome in ("right", "wrong", "unsure")}
    answered = counts["right"] + counts["wrong"]
    return {
        "bills": len(rows),
        **counts,
        "accuracy_when_it_answered": round(counts["right"] / answered, 3) if answered else None,
        "wrong_and_confident": sum(row["verdict"] == "wrong" and row["confidence"] == "high" for row in rows),
    }


async def main() -> None:
    rows: list[dict] = []
    async with create_recon_client("eval-bill-coding") as client:
        bills = list(
            await client.db.scalars(
                select(MoneyLine)
                .where(MoneyLine.kind == "vendor_bill", MoneyLine.job_id.is_not(None))
                .options(selectinload(MoneyLine.job))
                .order_by(MoneyLine.doc_number)
            )
        )
        for bill in bills:
            suggestion = await client.suggest_job(bill.id)
            row = {
                "bill": bill.doc_number,
                "actual": bill.job.job_number,
                "suggested": suggestion.job_number,
                "decision": suggestion.decision,
                "confidence": suggestion.confidence,
                "verdict": verdict(suggestion.decision, suggestion.job_number, bill.job.job_number),
                "lookups": len(suggestion.looked_at),
                "reasons": suggestion.reasons,
            }
            rows.append(row)
            print(f"{row['verdict']:7} {row['bill']:11} actual {row['actual']:12} suggested {row['suggested'] or row['decision']:14} {row['confidence']}")

    result = {"summary": summary(rows), "bills": rows}
    RESULTS.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["summary"], indent=2))
    print(f"Written to {RESULTS}")


if __name__ == "__main__":
    asyncio.run(main())
