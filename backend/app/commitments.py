"""Reading notes for commitments: what someone promised, or is waiting on, and by when.

People write things in notes that no check can see. "Payment scheduled on their next
check run, follow up Friday." "Customer asked for weekly photo updates." "Waiting on
the health department walkthrough." Each is a promise or a dependency with a date that
somebody has to keep track of today, in their head.

The agent reads a batch of notes and hands back each commitment as a typed record:
what kind it is, who made it, what it is and when it is due. It has no tools and sees
only the notes it is given. Our code checks every record before it is kept: it must
cite a note it was shown, and its date must make sense for that note. Whether a
commitment was kept is never the agent's call; it is worked out from the records.
"""

import json
import logging
from datetime import date, timedelta

from agents import Agent, Runner

from app import assistant
from app.schemas import CommitmentsReply

logger = logging.getLogger(__name__)

# A due date further from its note than this is a misreading, not a commitment.
LONGEST_AHEAD = timedelta(days=180)
# How many notes go to the model in one request.
BATCH = 20

INSTRUCTIONS = """\
You read notes that people at Harborstone, a commercial restoration contractor, wrote in
their project system and their accounting system. Find every commitment in them: something
someone has said will happen, that a person will need to check on later.

Four kinds:
- "payment_promised": the customer has said they will pay, or has scheduled payment.
- "promised_to_customer": the team has promised the customer something, such as updates,
  a visit, a document or a date.
- "waiting_on": the work is held up until someone outside the team does something, such as
  an inspector, a tenant, an insurer or a supplier.
- "we_will": a next step the team has said it will take, such as following up, escalating,
  scheduling or sending something.

For each one give:
- note_id: the note it is in.
- who: who made the promise or is being waited on, as the note names them ("the customer",
  "the health department", "Jenna Okafor"). The note's author is who wrote it.
- what: what was promised or is awaited, in a few plain words. Not a sentence about the note.
- due_on: the date it is due, as YYYY-MM-DD, only when the note gives one or a day that
  pins it down. Dates in a note are relative to the day it was written: "Friday" is the
  first Friday after that day, "next week" is the Monday of the following week, "one more
  week" is seven days after it. Leave it empty when the note gives no date.

Rules:
- Use only what the notes say. Never add a person, a date, an amount or an event.
- A note can hold several commitments, or none. A plain report of what happened, with
  nothing still to come, has none.
- One commitment once. If a note says both "follow up Friday" and "escalate next week",
  those are two.
"""


def brief(notes: list[dict]) -> str:
    """What the agent is shown: each note with its id, its date, who wrote it, where, and
    which job and invoice it is about. Built by our code; it can look nothing else up."""
    return json.dumps({"notes": notes}, ensure_ascii=False, default=str)


def checked(reply: CommitmentsReply, notes: list[dict]) -> list[dict]:
    """The commitments as they are kept. One that cites a note the agent was not shown is
    made up and is dropped; a date that does not fit its note is dropped and the commitment
    kept without one."""
    by_id = {note["note_id"]: note for note in notes}
    kept = []
    for found in reply.commitments:
        note = by_id.get(found.note_id)
        if note is None:
            logger.warning("Commitment reader cited note %s, which it was not shown", found.note_id)
            continue
        written = date.fromisoformat(str(note["written_on"]))
        due = None
        if found.due_on:
            try:
                due = date.fromisoformat(found.due_on)
            except ValueError:
                due = None
        if due is not None and (due < written or due - written > LONGEST_AHEAD):
            logger.warning("Commitment reader gave %s for a note written %s; date dropped", due, written)
            due = None
        what, who = found.what.strip(), found.who.strip()
        if not what or not who:
            continue
        kept.append({"note_id": found.note_id, "kind": found.kind, "who": who, "what": what, "due_on": due})
    return kept


async def read(notes: list[dict]) -> list[dict]:
    """Read notes for commitments, a batch at a time, and return them checked."""
    agent = Agent(
        name="Harborstone note reader",
        instructions=INSTRUCTIONS,
        model=assistant.build_model(),
        output_type=CommitmentsReply,
    )
    found: list[dict] = []
    for start in range(0, len(notes), BATCH):
        batch = notes[start : start + BATCH]
        result = await Runner.run(agent, brief(batch), max_turns=2)
        usage = result.context_wrapper.usage
        logger.info(
            "Note reader used requests=%s input_tokens=%s output_tokens=%s notes=%s",
            usage.requests, usage.input_tokens, usage.output_tokens, len(batch),
        )
        found.extend(checked(result.final_output, batch))
    return found
