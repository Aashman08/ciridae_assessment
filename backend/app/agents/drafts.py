"""Drafting a follow-up message about an issue.

The model writes the words. Everything else is fixed: who the message goes to,
their address and every fact it may use are chosen by our code and handed to
the model, which has no tools and cannot look anything else up. The draft is
then checked against those facts. Nothing is ever sent; a person copies it out.
"""

import json
import logging
from datetime import date
from typing import Any

from agents import Agent, Runner

from app.agents import assistant
from app.core.schemas import DraftReply, DraftResponse, Recipient

logger = logging.getLogger(__name__)

# The one issue type whose follow-up goes outside the company.
CUSTOMER_TYPES = ("past_due",)

INSTRUCTIONS = """\
You draft a short follow-up message for someone at Harborstone, a commercial
restoration contractor, about one problem found in its records. They will read
it, change it if they want, and send it themselves.

You are given the facts as JSON. Rules:
- Use only those facts. Never add a figure, date, name, invoice number or event
  that is not in them. If a fact you would like is missing, leave it out.
- Write every dollar amount in full, as given, such as $246,300.
- Name the invoice or bill by its number, and the job by its name, when given.
- Say what is being asked for, once, plainly: for a customer, when payment will be
  made; for a colleague, the specific thing only they can do.
- If the notes show earlier contact, refer to it in one sentence. Do not repeat it.
- Commitments are promises read from notes, each with its state. If one about this
  problem was missed, say so plainly in one sentence, such as "Payment was expected by
  31 July and has not arrived", and ask for a new date. Do not mention a kept one.
- Project notes are what the team wrote about the job. Mention one only if it bears on
  what is being asked.
- Make no promise or threat on Harborstone's behalf: no late fees, no stopping work,
  no discounts, no legal language.
- Courteous and direct. No apology for writing, no filler, no exclamation marks.
- Four to seven sentences. Plain text, no markdown, no placeholders in brackets.
- Greet the recipient by first name if one is given, otherwise by the name given.
  Close with the writer's name on its own line.
- {audience}
As of {as_of}. "Days late" is measured against that date.
"""

AUDIENCES = {
    "customer": "The recipient is the customer's billing contact. They are outside the company: do not mention "
    "Harborstone's internal systems, ledgers, syncs or issue lists.",
    "internal": "The recipient is a colleague at Harborstone. You may refer to the project system, the ledger and "
    "accounting by name.",
}


def _figures(value: Any, found: set[int]) -> set[int]:
    """Every number in the facts, in whole dollars, to check the draft against."""
    context = assistant.AskContext(client=None, owner=None)
    context._note(value)
    return found | context.figures


def check(draft: DraftReply, facts: dict, document: str | None) -> list[str]:
    """What a person should look at before sending. Empty when nothing stands out."""
    text = f"{draft.subject}\n{draft.body}"
    known = _figures(facts, set())
    warnings = []
    for match in assistant.DOLLARS.finditer(text):
        amount = int(match.group(1).replace(",", ""))
        if amount and amount not in known:
            warnings.append(f"{match.group(0)} is not a figure from the records")
    if assistant.BROKEN_FIGURE.search(text):
        warnings.append("A dollar figure is incomplete")
    if document and document not in text:
        warnings.append(f"{document} is not named in the message")
    if "[" in text or "]" in text:
        warnings.append("A placeholder in brackets was left in the message")
    return list(dict.fromkeys(warnings))


async def write(facts: dict, writer: str, recipient: Recipient, document: str | None, as_of: date) -> DraftResponse:
    """Draft the message, check it, and send it back once for correction if the check finds something."""
    agent = Agent(
        name="Harborstone follow-up drafter",
        instructions=INSTRUCTIONS.format(audience=AUDIENCES[recipient.audience], as_of=f"{as_of:%d %B %Y}"),
        model=assistant.build_model(),
        output_type=DraftReply,
    )
    brief = json.dumps(
        {
            "writer": writer,
            "recipient": {"name": recipient.name, "role": recipient.role},
            # Copied in, so the message can be read by them too. It is still written to the recipient.
            "copied": [{"name": person.name, "role": person.role} for person in recipient.cc],
            "facts": facts,
        },
        ensure_ascii=False,
    )
    result = await Runner.run(agent, brief, max_turns=2)
    draft: DraftReply = result.final_output
    warnings = check(draft, facts, document)
    if warnings:
        retry = result.to_input_list() + [
            {"role": "user", "content": "Write it again, fixing these: " + "; ".join(warnings) + ". Use only the facts given."}
        ]
        result = await Runner.run(agent, retry, max_turns=2)
        draft = result.final_output
        warnings = check(draft, facts, document)
        if warnings:
            logger.warning("Draft still has warnings after one retry: %s", warnings)

    usage = result.context_wrapper.usage
    logger.info("Draft used requests=%s input_tokens=%s output_tokens=%s", usage.requests, usage.input_tokens, usage.output_tokens)
    return DraftResponse(recipient=recipient, subject=draft.subject.strip(), body=draft.body.strip(), warnings=warnings, as_of=as_of)
