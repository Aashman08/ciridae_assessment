"""Turning a person's description of a check into something the app can run.

A person says what they want flagged, in their own words, and which kind of record it
is about. The assistant decides whether it can be tested on the fixed fields (then it
writes a rule over them), whether only reading notes can tell (a reading check), or
neither. It runs once, when the check is written; a rule then runs as code on every
sync. Whatever rule it writes is validated against the fields before anyone sees it.
"""

import json
import logging

from agents import Agent, Runner

from app import assistant
from app.rules import SUBJECT_WORDS, catalogue
from app.schemas import CheckDraftReply

logger = logging.getLogger(__name__)

INSTRUCTIONS = """\
You help someone at Harborstone, a commercial restoration contractor, set up a check: a
test the app runs on every sync that flags records needing attention. They describe what
they want flagged in their own words, and say which kind of record it is about. You are
given the fields that kind of record has.

Choose one approach:
- "rule" when the description can be tested on the fields given: amounts, statuses, days,
  yes/no facts. Write the rule: each condition compares one field with a value, or with
  another field (use "times" for a share, such as 1.1 for 110% of it). Use "all" when every
  condition must hold, "any" when one is enough. Set amount_field to the money field that
  says what is at stake, if one does. Amounts are in dollars. Days are whole days, counted
  to the date of the figures; "days past due" is negative while not yet due.
- "reading" when only what people wrote in notes can tell, such as a dispute, a complaint,
  a refusal, or someone saying something will slip.
- "cannot" when neither the fields nor notes could show it.

Rules:
- Use only the field names given, exactly. Never invent one.
- Text fields hold the values described, in capitals with underscores, such as IN_PROGRESS.
- Keep the rule as close to the person's words as the fields allow. If a part of what they
  asked cannot be tested, leave it out and say so in the reason.
- The reason is one plain sentence.
"""


async def draft(words: str, subject: str) -> CheckDraftReply:
    """Ask the assistant how to run what the person described. The caller validates any rule it returns."""
    agent = Agent(
        name="Harborstone check writer",
        instructions=INSTRUCTIONS,
        model=assistant.build_model(),
        output_type=CheckDraftReply,
    )
    brief = json.dumps(
        {"what_to_flag": words, "about_each": SUBJECT_WORDS[subject], "fields": catalogue(subject)},
        ensure_ascii=False,
    )
    result = await Runner.run(agent, brief, max_turns=2)
    usage = result.context_wrapper.usage
    logger.info("Check writer used requests=%s input_tokens=%s output_tokens=%s", usage.requests, usage.input_tokens, usage.output_tokens)
    return result.final_output
