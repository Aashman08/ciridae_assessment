"""Bill coding: working out which job a vendor bill belongs to.

A bill that is not tied to a job never reaches that job's cost, so the job's
profit is wrong until someone works out where it goes. This agent does the
working out and a person decides.

The agent gets the bill as it arrived (vendor, dates, line descriptions, the
subject of the email it came in on) and four fixed lookups. It never sees which
job a bill was coded to, for this bill or in any lookup about it, so the same
code can be scored against bills whose job is already known (see
`evals/bill_coding.py`). It must say when it is not sure, and it may conclude
that the bill is not a job cost at all.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from agents import Agent, RunContextWrapper, Runner, function_tool

from app import assistant
from app.errors import AskFailedError, InvalidRequestError
from app.schemas import AskStep, CodingReply, CodingResponse, CodingRunnerUp

logger = logging.getLogger(__name__)

MAX_TURNS = 10

INSTRUCTIONS = """\
You work out which job a vendor bill belongs to for the finance team at Harborstone,
a commercial restoration contractor. A person will check your answer before anything
is changed, so being clear about how sure you are matters more than always having an answer.

How to work:
- Start with the_bill. Then look at vendor_history and candidate_jobs. Use job_work on
  the two or three jobs that could fit, to see what kind of work and cost each one has.
- Evidence, strongest first: the bill's lines or its email subject name a site, building
  or scope that matches one job; the kind of work matches what a job is doing; the bill's
  date falls while the job was active; this vendor has billed that job before.
- A vendor having billed a job before is weak on its own. Vendors work on many jobs.
- Some bills are not job costs at all: statements, recurring services, and anything for
  Harborstone's own offices, branches or yard. Say so with not_a_job_cost.
- Use only what the lookups return. Never invent a job number, a site or a reason.

How to answer:
- decision "job" with the job number when the evidence points to one job.
- decision "not_a_job_cost" when the bill is overhead. Leave the job number empty.
- decision "unsure" when two or more jobs fit about equally, or nothing fits. Give the
  closest job as the runner-up if there is one.
- confidence "high" only when a line or the email names the job's site or scope and
  nothing contradicts it. "medium" when the kind of work and the dates fit one job best.
  "low" when you are choosing between similar jobs. A low-confidence job is a guess:
  prefer "unsure".
- Give two to four reasons, each one short sentence naming the evidence, such as a line
  description and the job detail it matches. Name the runner-up job if another came close.
"""


@dataclass
class CodingCase:
    """Everything the agent may look at for one bill, gathered by our code beforehand."""

    bill: dict
    vendor_history: list[dict]
    jobs: list[dict]
    work_by_job: dict[str, dict]
    steps: list[AskStep] = field(default_factory=list)

    def log(self, tool: str, **arguments: Any) -> None:
        self.steps.append(AskStep(tool=tool, arguments=arguments))


Ctx = RunContextWrapper[CodingCase]
lookup = function_tool(failure_error_function=assistant.tool_error)


@lookup
async def the_bill(ctx: Ctx) -> str:
    """The bill to be coded: vendor, number, date, total, each line's description and amount,
    and the subject of the email it arrived on when there is one."""
    ctx.context.log("the_bill")
    return json.dumps(ctx.context.bill, ensure_ascii=False)


@lookup
async def vendor_history(ctx: Ctx) -> str:
    """This vendor's other bills: number, date, total, line descriptions, and the job each
    one was coded to, if any."""
    ctx.context.log("vendor_history")
    return json.dumps(ctx.context.vendor_history, ensure_ascii=False)


@lookup
async def candidate_jobs(ctx: Ctx) -> str:
    """Every job the bill could belong to: number, name, customer, branch, kind of work,
    stage, and the dates it was won, started on site, completed and closed."""
    ctx.context.log("candidate_jobs")
    return json.dumps(ctx.context.jobs, ensure_ascii=False)


@lookup
async def job_work(ctx: Ctx, job_number: str) -> str:
    """What one job has been spending on: the cost entries its project team logged
    (what, when, how much) and the vendor bills already coded to it.

    Args:
        job_number: A job number from candidate_jobs, such as CTX00080002.
    """
    work = ctx.context.work_by_job.get(job_number.upper())
    if work is None:
        raise InvalidRequestError(f"There is no job {job_number} among the candidates. Use a number from candidate_jobs.")
    ctx.context.log("job_work", job_number=job_number.upper())
    return json.dumps(work, ensure_ascii=False)


LOOKUPS = [the_bill, vendor_history, candidate_jobs, job_work]


async def suggest(case: CodingCase) -> CodingResponse:
    """Run the agent on one bill and return its suggestion, checked against the candidates."""
    agent = Agent[CodingCase](
        name="Harborstone bill coder",
        instructions=INSTRUCTIONS,
        tools=LOOKUPS,
        model=assistant.build_model(),
        output_type=CodingReply,
    )
    result = await Runner.run(agent, "Which job does this bill belong to?", context=case, max_turns=MAX_TURNS)
    reply: CodingReply = result.final_output

    names = {job["job_number"]: job["name"] for job in case.jobs}
    job_number = (reply.job_number or "").upper() or None
    runner_up = (reply.runner_up_job_number or "").upper() or None
    # A job it names must be one it was shown. Anything else is made up and is refused.
    for named in (job_number, runner_up):
        if named and named not in names:
            logger.warning("Bill coder named job %s, which is not a candidate", named)
            raise AskFailedError()
    if reply.decision == "job" and not job_number:
        raise AskFailedError()
    if reply.decision == "job" and reply.confidence == "low":
        # A guess is not a suggestion. Show it as the closest fit and leave the decision open.
        reply.decision, runner_up, job_number = "unsure", runner_up or job_number, None
    if reply.decision != "job":
        job_number = None
    if runner_up == job_number:
        runner_up = None

    usage = result.context_wrapper.usage
    logger.info(
        "Bill coding used requests=%s input_tokens=%s output_tokens=%s lookups=%s",
        usage.requests, usage.input_tokens, usage.output_tokens, len(case.steps),
    )
    return CodingResponse(
        bill=case.bill["number"],
        decision=reply.decision,
        job_number=job_number,
        job_name=names.get(job_number) if job_number else None,
        confidence=reply.confidence,
        reasons=[reason.strip() for reason in reply.reasons if reason.strip()],
        runner_up=CodingRunnerUp(job_number=runner_up, job_name=names[runner_up]) if runner_up else None,
        looked_at=case.steps,
    )
