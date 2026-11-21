"""Score the note reader against commitments found by hand.

Every note in the export is put to the agent, and what it finds is compared with
what a person reading the same notes would write down. This calls the model once
(the five notes fit in one batch), so it needs OPENAI_API_KEY in backend/.env.
Nothing is stored: a run of this script does not change what the app shows.

    cd backend && uv run python -m evals.note_reading

All five notes were written on Friday 24 July 2026, so dates in them resolve as:
"Friday" is 31 July, "next week" and "Monday" are 27 July, "one more week" is 31 July.

Each expected commitment is matched by note and kind, and then by date. A note may
hold something a person could reasonably count or not (the crane booked for Monday);
those are listed as optional and count neither for nor against. Anything else the
agent finds is an extra: an extra commitment costs someone a look, so the number is
reported, but it is not as bad as a missed promise.
"""

import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from app.agents import commitments
from app.client import create_recon_client
from app.core.models import Job, Note

RESULTS = Path(__file__).parent / "note_reading_results.json"

# By the start of each note's text: (kind, allowed due dates), required then optional.
# None in the dates means "no date" is right.
EXPECTED = {
    "Moisture readings": {
        "required": [("we_will", {"2026-07-31"})],
        "optional": [("waiting_on", {"2026-07-31", None})],
    },
    "Dock leveler": {
        "required": [("promised_to_customer", {None})],
        "optional": [("we_will", {"2026-07-27", None})],
    },
    "Kitchen hood": {
        "required": [("waiting_on", {None})],
        "optional": [],
    },
    "Billing contact": {
        "required": [("payment_promised", {None, "2026-07-31"}), ("we_will", {"2026-07-31"})],
        "optional": [],
    },
    "Left voicemail": {
        "required": [("we_will", {"2026-07-27"})],
        "optional": [],
    },
}


def score(found: list[dict], notes: dict[int, str]) -> dict:
    rows, extras = [], 0
    by_note: dict[str, list[dict]] = {}
    for entry in found:
        start = next((key for key in EXPECTED if notes[entry["note_id"]].startswith(key)), None)
        by_note.setdefault(start or "?", []).append({**entry, "due_on": str(entry["due_on"]) if entry["due_on"] else None})

    for start, expected in EXPECTED.items():
        pool = list(by_note.get(start, []))
        for kind, dates in expected["required"]:
            match = next((c for c in pool if c["kind"] == kind), None)
            if match is None:
                rows.append({"note": start, "kind": kind, "verdict": "missed"})
                continue
            pool.remove(match)
            verdict = "right" if match["due_on"] in dates else "wrong date"
            rows.append({"note": start, "kind": kind, "verdict": verdict, "who": match["who"], "what": match["what"], "due_on": match["due_on"]})
        for kind, _dates in expected["optional"]:
            match = next((c for c in pool if c["kind"] == kind), None)
            if match:
                pool.remove(match)
        extras += len(pool)
    extras += len(by_note.get("?", []))

    counts = {outcome: sum(row["verdict"] == outcome for row in rows) for outcome in ("right", "wrong date", "missed")}
    return {"summary": {"expected": len(rows), **counts, "extras": extras}, "rows": rows}


async def main() -> None:
    async with create_recon_client("eval-note-reading") as client:
        rows = (
            await client.db.execute(select(Note, Job.job_number, Job.name).outerjoin(Job, Job.id == Note.job_id).order_by(Note.id))
        ).all()
        notes = [
            {
                "note_id": note.id, "written_on": note.written_at.date(), "written_by": note.written_by,
                "written_in": "project system" if note.source == "project" else "accounting",
                "job_number": job_number, "job_name": job_name, "invoice": note.document, "text": note.body,
            }
            for note, job_number, job_name in rows
        ]
        found = await client._with_model(commitments.read(notes))

    result = score(found, {note["note_id"]: note["text"] for note in notes})
    for row in result["rows"]:
        print(f"{row['verdict']:10} {row['note']:18} {row['kind']:22} {row.get('due_on') or '':10} {row.get('what', '')}")
    RESULTS.write_text(json.dumps({**result, "found": [{**c, "due_on": str(c["due_on"]) if c["due_on"] else None} for c in found]}, indent=2) + "\n")
    print(json.dumps(result["summary"], indent=2))
    print(f"Written to {RESULTS}")


if __name__ == "__main__":
    asyncio.run(main())
