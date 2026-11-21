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
from app.rules import FIELDS, catalogue
from app.schemas import CheckDraftReply

logger = logging.getLogger(__name__)

INSTRUCTIONS = """\
You help someone at Harborstone, a commercial restoration contractor, set up a check: a
test the app runs on every sync that flags records needing attention. They describe what
they want flagged in their own words. You are given the fields each kind of record has.

Work out from their words:
- subject: what it looks at. "job" for something about a job as a whole, "customer_invoice"
  for one invoice to a customer, "vendor_bill" for one bill from a vendor, "customer" for a
  customer across all their invoices and jobs, "vendor" for a vendor across all their bills.
- title: a short name for the check in sentence case, such as "Large invoice still open".
- about: cash, billing, cost, schedule or ownership.
- severity: "high" when money is at risk now or a deadline is close, otherwise "medium".

Then choose one approach:
- "rule" when the description can be tested on the fields given: amounts, statuses, days,
  yes/no facts. Write the rule: each condition compares one field with a value, or with
  another field (use "times" for a share, such as 1.1 for 110% of it). Use "all" when every
  condition must hold, "any" when one is enough. For text, "contains" and
  "does_not_contain" match a word anywhere in it, such as a bill's lines mentioning "roof". Set amount_field to the money field that
  says what is at stake, if one does. Amounts are in dollars. Days are whole days, counted
  to the date of the figures; "days past due" is negative while not yet due.
- "reading" when only what people wrote in notes can tell, such as a dispute, a complaint,
  a refusal, or someone saying something will slip.
- "cannot" when neither the fields nor notes could show it.

Rules:
- Use only the field names given for the subject you chose, exactly. Never invent one.
- For a text field compared with "=" or "!=", use one of its values_today exactly.
- Keep the rule as close to the person's words as the fields allow. If a part of what they
  asked cannot be tested, leave it out and say so in the reason.
- The reason is one plain sentence.
"""


async def draft(words: str, values: dict[str, dict[str, list[str]]]) -> CheckDraftReply:
    """Ask the assistant how to run what the person described. The caller validates any rule it returns."""
    agent = Agent(
        name="Harborstone check writer",
        instructions=INSTRUCTIONS,
        model=assistant.build_model(),
        output_type=CheckDraftReply,
    )
    brief = json.dumps(
        {"what_to_flag": words, "fields_by_subject": {subject: catalogue(subject, values.get(subject)) for subject in FIELDS}},
        ensure_ascii=False,
    )
    result = await Runner.run(agent, brief, max_turns=2)
    usage = result.context_wrapper.usage
    logger.info("Check writer used requests=%s input_tokens=%s output_tokens=%s", usage.requests, usage.input_tokens, usage.output_tokens)
    return result.final_output
