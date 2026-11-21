"""Checks people add that only reading can answer.

Some things are written, not recorded in any figure: a customer disputing an invoice,
a tenant refusing access, a supplier saying a delivery will slip. A reading check is
a person's description of one of those. The assistant reads the notes on each job or
invoice for it and says which ones it applies to, quoting the words that show it.

Our code checks every quote against the notes it was given and drops any it cannot
find, so a finding always rests on words someone actually wrote. What the assistant
decided is kept per check and per job or invoice, with the text it read, and the
notes are only read again when that text changes. On a sync, a reading check's
findings come from what is kept, so a sync itself never calls the model.
"""

import hashlib
import json
import logging
import re
from collections import defaultdict
from decimal import Decimal

from agents import Agent, Runner
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import assistant
from app.issues import OWNER, Finding, line
from app.models import CheckReading, IssueType, Job, Note, SyncRun
from app.schemas import ReadingReply

logger = logging.getLogger(__name__)

BATCH = 15

INSTRUCTIONS = """\
You check notes written at Harborstone, a commercial restoration contractor, against one
check a person has described. For each job or invoice you are given its notes. Say which
ones the check applies to.

For each one it applies to, give:
- subject: its job number or invoice number, exactly as given.
- quote: the exact words from its notes that show the check applies, copied character
  for character. Not a summary.
- reason: one sentence on why those words match the check.

Rules:
- Only flag what the notes say. A guess about what might be true is not a match.
- Leave out every job or invoice the check does not apply to. An empty list is a fine answer.
"""


def _same(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


async def texts(db: AsyncSession, subject: str) -> dict[str, str]:
    """The notes on each job or invoice, as one block of text each, oldest first."""
    query = select(Note, Job.job_number).outerjoin(Job, Job.id == Note.job_id).order_by(Note.written_at, Note.id)
    if subject == "customer_invoice":
        query = query.where(Note.document.is_not(None))
    by: dict[str, list[str]] = defaultdict(list)
    for note, job_number in await db.execute(query):
        key = note.document if subject == "customer_invoice" else job_number
        if key:
            where = "project system" if note.source == "project" else f"accounting, on {note.document}"
            by[key].append(f"{note.written_at:%d %b %Y}, {note.written_by}, {where}: {note.body}")
    return {key: "\n".join(lines) for key, lines in by.items()}


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def checked(reply: ReadingReply, shown: dict[str, str]) -> dict[str, dict]:
    """Only flags on a job or invoice it was shown, quoting words that are in its notes."""
    kept: dict[str, dict] = {}
    for flag in reply.flagged:
        text = shown.get(flag.subject)
        if text is None:
            logger.warning("Reading check flagged %s, which it was not shown", flag.subject)
            continue
        if _same(flag.quote) not in _same(text):
            logger.warning("Reading check quote for %s is not in its notes; dropped", flag.subject)
            continue
        kept[flag.subject] = {"quote": flag.quote.strip(), "reason": flag.reason.strip()}
    return kept


async def read(instruction: str, subject: str, shown: dict[str, str]) -> dict[str, dict]:
    """Have the assistant read these notes for one check. Returns the flags that survived checking."""
    agent = Agent(
        name="Harborstone reading check",
        instructions=INSTRUCTIONS,
        model=assistant.build_model(),
        output_type=ReadingReply,
    )
    kind = "invoice" if subject == "customer_invoice" else "job"
    flags: dict[str, dict] = {}
    keys = sorted(shown)
    for start in range(0, len(keys), BATCH):
        batch = {key: shown[key] for key in keys[start : start + BATCH]}
        brief = json.dumps({"check": instruction, f"{kind}s": [{"subject": k, "notes": v} for k, v in batch.items()]}, ensure_ascii=False)
        result = await Runner.run(agent, brief, max_turns=2)
        usage = result.context_wrapper.usage
        logger.info("Reading check used requests=%s input_tokens=%s output_tokens=%s subjects=%s", usage.requests, usage.input_tokens, usage.output_tokens, len(batch))
        flags.update(checked(result.final_output, batch))
    return flags


async def from_readings(
    db: AsyncSession, run: SyncRun, issue_type: IssueType, readings: list[CheckReading] | None = None
) -> list[Finding]:
    """A reading check's findings on a sync: what the assistant last decided, for records that still exist.
    `readings` lets a check being tried out show its findings without anything being kept."""
    if readings is None:
        readings = list(await db.scalars(select(CheckReading).where(CheckReading.type_key == issue_type.key, CheckReading.flagged)))
    if not readings:
        return []
    subjects = [r.subject for r in readings]
    found = []
    if issue_type.subject == "customer_invoice":
        rows = {
            r.doc_number: r
            for r in await db.execute(
                select(line.id, line.doc_number, (line.amount - line.paid_amount).label("open_amount"), Job.id.label("job_id"), OWNER)
                .outerjoin(Job, Job.id == line.job_id)
                .where(line.kind == "customer_invoice", line.doc_number.in_(subjects))
            )
        }
    else:
        rows = {
            r.job_number: r
            for r in await db.execute(select(Job.id.label("job_id"), Job.job_number, OWNER).where(Job.job_number.in_(subjects)))
        }
    for reading in readings:
        row = rows.get(reading.subject)
        if row is None:
            continue
        on_invoice = issue_type.subject == "customer_invoice"
        found.append(
            Finding(
                issue_type.key, reading.subject, Decimal(row.open_amount) if on_invoice else Decimal(0),
                summary=issue_type.title,
                detail=f"The notes say: “{reading.quote}”. {reading.reason}",
                next_step="Look into it and say what is behind it.", action_label="Ask about it",
                owner=row.owner, job_id=row.job_id, document=reading.subject if on_invoice else None,
                evidence=[row.id] if on_invoice else [],
            )
        )
    return found
