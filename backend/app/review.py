"""Reviewing a job's items: should each one be acted on now, left until a date, or dismissed?

Fixed rules already say what work fixes each kind of item. What rules cannot do
is read. A note may say the customer has promised payment on Friday, in which
case chasing again today is the wrong move; a cost gap may be too small to be
worth anyone's time. The agent reads the items with their notes and history and
gives one of three answers for each, with its reason, and picks the item to
start with.

It cannot invent an action. For each item it may only say act (do the work the
rules name), wait until a date, or dismiss. A person confirms before anything
happens.
"""

import json
import logging
from datetime import date, timedelta

from agents import Agent, Runner

from app import assistant
from app.errors import AskFailedError
from app.items import working_days_from
from app.schemas import ItemAction, ItemResponse, JobSuggestion, ReviewReply, Suggestion

logger = logging.getLogger(__name__)

# How long a follow-up runs when no better date is known.
FOLLOW_UP_WORKING_DAYS = 5
# A date further out than this is not a follow-up, it is forgetting.
LONGEST_WAIT = timedelta(days=60)

INSTRUCTIONS = """\
You review the open problems on one job for Harborstone, a commercial restoration
contractor, and say what should happen to each next. A person reads your review and
confirms before anything is done.

For each item you are given what is wrong, its tags, the amount, who has it, the
notes people have left with their dates, and the work that normally fixes it.

Answer for every item with one decision:
- "act": do the work named for the item now. This is the answer unless the notes or
  the figures give a reason for one of the other two.
- "wait": someone has already acted and a reply or a date is pending. Give the date
  to come back, as YYYY-MM-DD, after today. Use a date from the notes when there is
  one. Only choose this when a note supports it.
- "dismiss": nothing needs doing. Use this sparingly: when a gap is trivial next to
  the job's size, or a note explains it and it is expected. Never dismiss an unpaid
  invoice or bill.

Then name the one item to deal with first: the one where delay costs the most. Money
at risk, a deadline, and how late something already is all count. Items already
waiting do not come first.

Rules:
- Use only what you are given. Never add a figure, a date, a name or an event.
- Each reason is one plain sentence that names the evidence, such as the note it
  rests on or the tag that makes it urgent. No general advice.
- Notes are dated. A promise whose date has passed with nothing since is a reason to
  act, not to wait.
- The job's project notes are background. Use them only if they bear on an item.
- The job's commitments are promises and waits read from notes, each with where it stands:
  missed, due_soon, open, kept or done. A missed payment promise is a strong reason to act
  now and to say the promise was missed. One that is due soon and still open is a reason to
  wait until its date. A kept one needs nothing.
- Today is {today}, the date the figures are as of. "Days late" is measured against it,
  and so are the dates in notes: "Friday" in a note means the Friday after the note's date.
"""


def brief(job: dict, items: list[ItemResponse]) -> str:
    """What the agent is shown about a job. Built by our code; it has no tools and can look nothing else up."""
    return json.dumps(
        {
            "job": job,
            "items": [
                {
                    "item_key": item.key,
                    "what": item.title,
                    "document": item.document,
                    "company": item.company,
                    "amount": str(item.amount),
                    "severity": item.severity,
                    "tags": [tag.label for tag in item.tags],
                    "what_is_wrong": item.details,
                    "has_it": item.owner,
                    "already_waiting_until": str(item.follow_up_on) if item.follow_up_on else None,
                    "work_that_fixes_it": item.action.label,
                    "notes": [
                        *({"by": note.by, "on": str(note.on), "kind": "note in accounting", "note": note.note} for note in item.source_notes),
                        *(
                            {"by": event.actor, "on": str(event.created_at.date()), "kind": event.kind, "note": event.note}
                            for event in item.events
                            if event.kind in ("commented", "assigned", "follow_up", "suggested") and event.note
                        ),
                    ],
                }
                for item in items
            ],
        },
        ensure_ascii=False,
    )


def checked(reply: ReviewReply, items: list[ItemResponse], today: date) -> dict:
    """The review as it is stored: only items that exist, only dates that make sense.
    Anything the agent names that it was not shown is made up, and the whole review is refused."""
    known = {item.key: item for item in items}
    reviewed: dict[str, dict] = {}
    for entry in reply.items:
        item = known.get(entry.item_key)
        if item is None:
            logger.warning("Review named item %s, which is not on the job", entry.item_key)
            raise AskFailedError()
        decision, until = entry.decision, None
        if decision == "dismiss" and item.kind in ("invoice_unpaid", "bill_stuck", "invoice_not_sent"):
            # Money owed is never waved away on the assistant's say-so.
            decision = "act"
        if decision == "wait":
            try:
                until = date.fromisoformat(entry.wait_until or "")
            except ValueError:
                until = None
            if until is None or until <= today or until - today > LONGEST_WAIT:
                until = working_days_from(today, FOLLOW_UP_WORKING_DAYS)
        reviewed[entry.item_key] = {"decision": decision, "until": str(until) if until else None, "reason": entry.reason.strip()}

    first = reply.first_item_key
    if first is not None and (first not in known or reviewed.get(first, {}).get("decision") == "wait"):
        first = None
    return {"items": reviewed, "first": first, "why_first": (reply.why_first or "").strip() or None}


def suggestion_for(item: ItemResponse, entry: dict) -> Suggestion:
    """An item's suggested next step, from a stored review of it."""
    if entry["decision"] == "wait":
        until = date.fromisoformat(entry["until"])
        action = ItemAction(key="wait", label=f"Wait until {until.day} {until:%b}")
        return Suggestion(action=action, reason=entry["reason"], follow_up_on=until, by="assistant")
    if entry["decision"] == "dismiss":
        action = ItemAction(key="dismiss", label="Dismiss as expected")
        return Suggestion(action=action, reason=entry["reason"], follow_up_on=None, by="assistant")
    return Suggestion(action=item.action, reason=entry["reason"], follow_up_on=None, by="assistant")


def first_from(review: dict, items: list[ItemResponse]) -> JobSuggestion | None:
    by_key = {item.key: item for item in items}
    first = by_key.get(review.get("first") or "")
    if first is None or first.state != "needs_action":
        return None
    return JobSuggestion(item_key=first.key, action=first.suggestion.action, reason=review.get("why_first"), by="assistant")


async def review(job: dict, items: list[ItemResponse], as_of: date) -> dict:
    """Ask the agent about one job's items and return its checked answer. The date of the
    last sync is today as far as the review is concerned, because that is when the figures are from."""
    today = as_of
    agent = Agent(
        name="Harborstone job reviewer",
        instructions=INSTRUCTIONS.format(today=f"{today:%A %d %B %Y}"),
        model=assistant.build_model(),
        output_type=ReviewReply,
    )
    result = await Runner.run(agent, brief(job, items), max_turns=2)
    usage = result.context_wrapper.usage
    logger.info(
        "Review used requests=%s input_tokens=%s output_tokens=%s items=%s",
        usage.requests, usage.input_tokens, usage.output_tokens, len(items),
    )
    return checked(result.final_output, items, today)
