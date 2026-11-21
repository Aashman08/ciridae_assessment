"""Ask: the model may only pick a fixed tool and fill in its inputs.

These tests drive the real agent loop with a scripted stand-in for the model,
so they need no API key and no network. The stand-in plays the model's side
(which tool to call, what to say); everything else is the production code.
"""

import json
from decimal import Decimal

import pytest
from agents import ModelResponse, Usage
from agents.models.interface import Model
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText

from app.agents import assistant

from app.core import database
from app.core.errors import AskFailedError, AskNotConfiguredError
from app.core.schemas import AskRequest, IssueFilters

pytestmark = pytest.mark.usefixtures("synced")
API = "/api/v1"
TASHA = "Tasha Green"


def call(name: str, **arguments) -> ResponseFunctionToolCall:
    """The model deciding to use a tool."""
    return ResponseFunctionToolCall(
        arguments=json.dumps(arguments), call_id=f"call_{name}_{len(arguments)}", name=name, type="function_call"
    )


def reply(*blocks: dict) -> ResponseOutputMessage:
    """The model giving its final answer, as the blocks it must use."""
    return ResponseOutputMessage(
        id="msg_1", role="assistant", status="completed", type="message",
        content=[ResponseOutputText(annotations=[], text=json.dumps({"blocks": list(blocks)}), type="output_text")],
    )


def say_block(text: str) -> dict:
    return {"type": "text", "text": text}


def say(text: str) -> ResponseOutputMessage:
    """The model answering in one sentence."""
    return reply({"type": "text", "text": text})


class ScriptedModel(Model):
    """Plays back a fixed list of model turns and records what it was sent."""

    def __init__(self, *turns):
        self.turns = list(turns)
        self.requests: list[dict] = []

    async def get_response(self, system_instructions, input, model_settings, tools, output_schema, handoffs, tracing, **_):
        self.requests.append({"instructions": system_instructions, "input": list(input), "tools": [t.name for t in tools]})
        turn = self.turns.pop(0) if len(self.turns) > 1 else self.turns[0]
        return ModelResponse(output=[turn], usage=Usage(), response_id=None)

    def stream_response(self, *args, **kwargs):
        raise NotImplementedError

    def tool_results(self) -> list[str]:
        """Every tool result the loop handed back to the model, in order."""
        last = self.requests[-1]["input"]
        return [item["output"] for item in last if isinstance(item, dict) and item.get("type") == "function_call_output"]


@pytest.fixture
def model(monkeypatch):
    """Turn Ask on and let a test script the model."""
    monkeypatch.setattr(database.settings, "openai_api_key", "test-key")

    def use(*turns) -> ScriptedModel:
        scripted = ScriptedModel(*turns)
        monkeypatch.setattr(assistant, "build_model", lambda: scripted)
        return scripted

    return use


async def test_ask_says_so_when_no_key_is_set(recon, api):
    with pytest.raises(AskNotConfiguredError):
        await recon.ask(AskRequest(question="What is owed?"))
    response = await api.post(f"{API}/ask", json={"question": "What is owed?"})
    assert response.status_code == 503
    assert response.json()["error"]["type"] == "ask_not_configured"
    assert "OPENAI_API_KEY" in response.json()["error"]["message"]


async def test_the_model_only_gets_the_fixed_tools(recon, model):
    scripted = model(say("Nothing to report."))
    await recon.ask(AskRequest(question="Anything?"))
    assert scripted.requests[0]["tools"] == [
        "company_summary", "list_jobs", "get_job", "list_issues", "get_issue", "list_issue_types",
        "list_invoices", "list_vendor_bills", "owed_by_customer", "totals_by_month",
    ]
    # Nothing that takes SQL, a table name or free text to run.
    for tool in assistant.TOOLS:
        assert not {"sql", "query", "table", "where"} & set(tool.params_json_schema.get("properties", {}))


async def test_a_question_runs_tool_then_answer(recon, model):
    scripted = model(
        call("owed_by_customer", limit=3),
        say("Northgate Independent School District owes the most: $246,300, all of it past due."),
    )
    result = await recon.ask(AskRequest(question="Which customer owes us the most?"))

    assert result.answer.startswith("Northgate Independent School District owes the most")
    assert [(s.tool, s.arguments) for s in result.steps] == [("owed_by_customer", {"limit": 3})]
    assert str(result.as_of) == "2026-07-28"

    # The figures the model answered from are the ones our own query returned.
    balances = json.loads(scripted.tool_results()[0])
    assert balances[0] == {
        "customer": "Northgate Independent School District", "open_invoice_count": 1,
        "owed": "246300.00", "past_due": "246300.00",
    }
    assert len(balances) == 3


async def test_the_model_is_told_the_date_and_the_rules(recon, model):
    scripted = model(say("Done."))
    await recon.ask(AskRequest(question="Hello"))
    instructions = scripted.requests[0]["instructions"]
    assert "28 July 2026" in instructions
    assert "Every figure you state must come from a tool result" in instructions
    assert "sees every job" in instructions


async def test_a_job_looked_up_directly_is_always_cited(recon, model):
    model(
        call("get_job", job_number="CTX00080002", revenue_basis="ledger", cost_basis="ops_log"),
        say("Profit is $104,900 using ledger revenue and the ops log cost."),
    )
    result = await recon.ask(AskRequest(question="What did the Redbird dock job make?"))
    assert [(s.kind, s.id, s.label) for s in result.sources] == [
        ("job", "CTX00080002", "CTX00080002 Redbird — Building A Dock Rebuild")
    ]
    assert result.steps[0].arguments == {"job_number": "CTX00080002", "revenue_basis": "ledger", "cost_basis": "ops_log"}


async def test_listed_records_are_cited_only_when_the_answer_names_them(recon, model):
    model(
        call("list_invoices", limit=25),
        say("The largest unpaid invoice is INV-2026-0538 on job RTX00050002, with $246,300 open."),
    )
    result = await recon.ask(AskRequest(question="What is our largest unpaid invoice?"))
    assert [(s.kind, s.id, s.label) for s in result.sources] == [("invoice", "RTX00050002", "INV-2026-0538")]


async def test_tool_inputs_are_checked_before_anything_runs(recon, model):
    scripted = model(call("list_jobs", stage="ALMOST_DONE"), say("I could not filter by that stage."))
    result = await recon.ask(AskRequest(question="Which jobs are almost done?"))
    # The bad input never reached our query; the model was told what the tool accepts instead.
    told = scripted.tool_results()[0]
    assert told.startswith("Those inputs are not valid for list_jobs")
    assert "WORK_NOT_STARTED" in told and "IN_PROGRESS" in told
    assert result.steps == []


async def test_someone_who_sees_only_their_jobs_is_limited_whatever_the_model_asks(recon, model):
    scripted = model(
        call("list_jobs", limit=25),
        call("get_job", job_number="CTX00080002"),  # Ray Delgado's job, not Tasha's
        call("company_summary"),
        say("You have 6 jobs."),
    )
    await recon.ask(AskRequest(question="Show me everything", owner=TASHA))

    jobs, other_job, summary = scripted.tool_results()
    listed = json.loads(jobs)
    assert listed["total"] == 6
    assert {j["ops_manager"] for j in listed["jobs"]} == {TASHA}
    assert "No job found with number 'CTX00080002'" in other_job
    assert json.loads(summary)["cash"]["owed"] == "639700.00"
    assert "only sees their own jobs" in scripted.requests[0]["instructions"]


async def test_ask_knows_which_page_it_was_opened_from(recon, api, model):
    """Asked from a job's page, "this job" means that job. The page only points at
    records; what the person may see is still decided by the tools."""
    from app.core.schemas import AskPage

    scripted = model(call("get_job", job_number="CTX00080002"), say("It has 4 open issues."))
    await recon.ask(AskRequest(question="What is wrong with this job?", page=AskPage(kind="job", job_number="CTX00080002")))
    assert 'has job CTX00080002 open. "This job" or "it" means that job' in scripted.requests[0]["instructions"]

    issue_id = (await recon.list_issues(IssueFilters(owner=TASHA, limit=1))).data[0].id
    scripted = model(call("get_issue", issue_id=issue_id), say("It is a past due invoice."))
    result = await recon.ask(AskRequest(question="Explain this", owner=TASHA, page=AskPage(kind="issue", issue_id=issue_id)))
    assert f"has issue {issue_id} open" in scripted.requests[0]["instructions"]
    looked_up = json.loads(scripted.tool_results()[0])
    assert looked_up["id"] == issue_id and looked_up["owner"] == TASHA and "history" in looked_up
    assert [s.kind for s in result.sources if s.kind == "issue"] == ["issue"]

    # Pointing at someone else's issue from the page does not get past the scope.
    other = (await recon.list_issues(IssueFilters(owner="Ray Delgado", limit=1))).data[0].id
    scripted = model(call("get_issue", issue_id=other), say("I cannot find that issue."))
    await recon.ask(AskRequest(question="Explain this", owner=TASHA, page=AskPage(kind="issue", issue_id=other)))
    assert f"No issue found with id {other}" in scripted.tool_results()[0] or "not found" in scripted.tool_results()[0].lower()

    scripted = model(say("5 are unsent."))
    await recon.ask(AskRequest(question="Summarise these", page=AskPage(kind="invoices", filters={"status": "DRAFT"})))
    assert "looking at the list of customer invoices, filtered to status = DRAFT" in scripted.requests[0]["instructions"]

    scripted = model(say("Hello."))
    await recon.ask(AskRequest(question="Hello"))
    assert "asking from the Ask page" in scripted.requests[0]["instructions"]

    # The page cannot carry free text or SQL into the instructions.
    for bad in ({"kind": "job", "job_number": "x; drop table"}, {"kind": "sql"}, {"kind": "jobs", "filters": {"q": "x" * 61}}):
        assert (await api.post(f"{API}/ask", json={"question": "Hi", "page": bad})).status_code == 422


async def test_a_conversation_is_saved_and_still_there_later(recon, model):
    """Leaving and coming back must not lose the conversation."""
    model(call("company_summary"), say("Customers owe $1,477,564."))
    saved = await recon.ask(AskRequest(question="How much are we owed?", asked_by="Rachel Kim"))
    assert saved.id > 0 and saved.created_at is not None

    history = await recon.list_ask_history("Rachel Kim")
    assert [(e.question, e.answer) for e in history] == [("How much are we owed?", "Customers owe $1,477,564.")]
    assert [s.tool for s in history[0].steps] == ["company_summary"]
    # Each person has their own conversation.
    assert await recon.list_ask_history("Tasha Green") == []

    await recon.clear_ask_history("Rachel Kim")
    assert await recon.list_ask_history("Rachel Kim") == []


async def test_earlier_exchanges_are_sent_with_the_new_question(recon, model):
    person = "Follow-up Tester"
    model(say("INV-2026-0538, with $246,300 open."))
    await recon.ask(AskRequest(question="What is our largest unpaid invoice?", asked_by=person))

    scripted = model(say("Yes, RTX00050002."))
    await recon.ask(AskRequest(question="Is that one of Tasha's?", asked_by=person))
    sent = [(m["role"], m["content"]) for m in scripted.requests[0]["input"]]
    assert sent == [
        ("user", "What is our largest unpaid invoice?"),
        ("assistant", "INV-2026-0538, with $246,300 open."),
        ("user", "Is that one of Tasha's?"),
    ]


async def test_a_failed_question_is_not_saved(recon, model):
    person = "Unlucky Asker"
    model(call("company_summary"))  # never answers
    with pytest.raises(AskFailedError):
        await recon.ask(AskRequest(question="Loop", asked_by=person))
    assert await recon.list_ask_history(person) == []


async def test_a_model_that_never_answers_is_stopped(recon, model):
    model(call("company_summary"))  # asks for the same tool forever
    with pytest.raises(AskFailedError):
        await recon.ask(AskRequest(question="Loop"))


async def test_figures_the_assistant_calculated_are_called_out(recon, model):
    """The reader can tell a figure read from the data from one worked out on top of it."""
    model(
        call("owed_by_customer", limit=2),
        say("Northgate owes $246,300 and Redbird owes $194,900. Together that is $441,200."),
    )
    result = await recon.ask(AskRequest(question="What do our two biggest debtors owe together?"))
    # The two balances were read from the data. Their sum was not.
    assert result.worked_out == ["$441,200"]


async def test_an_incomplete_figure_is_sent_back_once(recon, model):
    scripted = model(
        call("company_summary"),
        say("Customers owe $1,477,? in total."),
        say("Customers owe $1,477,564 in total."),
    )
    result = await recon.ask(AskRequest(question="How much are we owed?"))
    assert result.answer == "Customers owe $1,477,564 in total."
    assert result.worked_out == []
    # The model was told what was wrong, and the lookup was not repeated.
    assert "incomplete dollar figure" in scripted.requests[-1]["input"][-1]["content"]
    assert [s.tool for s in result.steps] == ["company_summary"]


async def test_an_answer_that_stays_broken_is_not_passed_on(recon, model):
    model(say("We are owed $?"))
    with pytest.raises(AskFailedError):
        await recon.ask(AskRequest(question="How much are we owed?"))


async def test_an_answer_can_carry_a_table_and_figures(recon, api, model):
    lead = {"type": "text", "text": "2 customers owe the most."}
    table = {
        "type": "table",
        "columns": [{"label": "Customer", "kind": "text"}, {"label": "Owed", "kind": "money"}],
        "rows": [["Northgate Independent School District", "$246,300"], ["Redbird", "$194,900"]],
    }
    figures = {"type": "figures", "items": [{"label": "Together", "value": "$441,200"}]}
    model(call("owed_by_customer", limit=2), reply(lead, table, figures))
    body = (await api.post(f"{API}/ask", json={"question": "Who owes most?", "asked_by": "Table Reader"})).json()

    # The display spec holds only the fixed element types, in the order written.
    spec = body["spec"]
    assert spec["root"] == "answer"
    assert spec["elements"]["answer"] == {"type": "Answer", "props": {}, "children": ["block-1", "block-2", "block-3"]}
    assert [spec["elements"][key]["type"] for key in spec["elements"]["answer"]["children"]] == ["Text", "Table", "Figures"]
    assert spec["elements"]["block-2"]["props"] == {"columns": table["columns"], "rows": table["rows"]}

    # Figures inside a table or a figures block are checked like any others.
    assert body["worked_out"] == ["$441,200"]
    assert body["answer"] == (
        "2 customers owe the most.\n\n"
        "Northgate Independent School District, $246,300\nRedbird, $194,900\n\n"
        "Together: $441,200"
    )
    saved = (await api.get(f"{API}/ask/history", params={"asked_by": "Table Reader"})).json()
    assert saved[0]["spec"] == spec


async def test_a_chart_is_drawn_from_monthly_totals_worked_out_in_sql(recon, api, db, model):
    """Asked for a graph, the model gets the month totals from a fixed query and
    hands back a chart block. The plotted figures are checked like any others."""
    from sqlalchemy import text

    expected = [
        (month, float(amount), float(sent))
        for month, amount, sent in await db.execute(text(
            "select to_char(line_date, 'YYYY-MM'), sum(amount), "
            "coalesce(sum(amount) filter (where status = 'SENT'), 0) "
            "from recon.money_line where kind = 'customer_invoice' group by 1 order by 1"
        ))
    ]
    chart = {
        "type": "chart", "kind": "line", "title": "Invoiced by month", "unit": "money",
        "points": [month for month, _, _ in expected],
        "series": [
            {"label": "Invoiced", "values": [amount for _, amount, _ in expected]},
            {"label": "Sent", "values": [sent for _, _, sent in expected]},
        ],
    }
    scripted = model(call("totals_by_month", kind="customer_invoices"), reply(say_block("Invoicing by month."), chart))
    body = (await api.post(f"{API}/ask", json={"question": "Graph invoicing by month", "asked_by": "Chart Reader"})).json()

    months = json.loads(scripted.tool_results()[0])
    assert [(m["month"], float(m["amount"]), float(m["sent"])) for m in months] == expected
    assert sum(m["count"] for m in months) == 21

    drawn = body["spec"]["elements"]["block-2"]
    assert drawn["type"] == "Chart"
    assert drawn["props"] == {key: value for key, value in chart.items() if key != "type"}
    # Every plotted figure came straight from the tool, so none is flagged as calculated.
    assert body["worked_out"] == []
    assert body["steps"] == [{"tool": "totals_by_month", "arguments": {"kind": "customer_invoices"}}]


async def test_month_totals_are_limited_to_a_persons_own_jobs(recon):
    everyone = await recon.list_month_totals("customer_invoice")
    mine = await recon.list_month_totals("customer_invoice", TASHA)
    assert sum(m.amount for m in mine) < sum(m.amount for m in everyone)
    assert sum(m.unpaid for m in everyone) == Decimal("1477564.00")
    assert sum(m.unpaid for m in mine) == Decimal("639700.00")
    assert all(m.sent == 0 for m in await recon.list_month_totals("vendor_bill"))


async def test_a_figure_followed_by_a_comma_is_read_whole(recon, model):
    model(call("owed_by_customer", limit=2), say("Northgate owes $246,300, Redbird owes $194,900, and that is all."))
    result = await recon.ask(AskRequest(question="Who owes?"))
    assert result.worked_out == []


async def test_a_reply_outside_the_fixed_blocks_is_refused(recon, model):
    person = "Layout Inventor"
    for bad in (
        {"type": "pie", "slices": [1, 2, 3]},
        {
            "type": "chart", "kind": "line", "title": "Lopsided", "unit": "money",
            "points": ["May", "June"], "series": [{"label": "Invoiced", "values": [1.0]}],
        },
        {"type": "table", "columns": [{"label": "Job", "kind": "text"}], "rows": [["RTX00050002", "extra"]]},
    ):
        model(reply(bad))
        with pytest.raises(AskFailedError):
            await recon.ask(AskRequest(question="Draw it", asked_by=person))
    assert await recon.list_ask_history(person) == []


def drafted(subject: str, body: str) -> ResponseOutputMessage:
    """The model handing back a follow-up message."""
    return ResponseOutputMessage(
        id="msg_1", role="assistant", status="completed", type="message",
        content=[ResponseOutputText(annotations=[], text=json.dumps({"subject": subject, "body": body}), type="output_text")],
    )


async def issue_about(api, document: str) -> dict:
    issues = (await api.get(f"{API}/issues", params={"limit": 100})).json()["data"]
    return next(i for i in issues if i["document"] == document)


async def test_a_late_invoice_follow_up_goes_to_the_customers_billing_contact(api, model):
    """Who it goes to and what it may say come from the records. The model only writes."""
    issue = await issue_about(api, "INV-2026-0538")
    scripted = model(drafted(
        "Invoice INV-2026-0538, $246,300 past due",
        "Hello,\n\nInvoice INV-2026-0538 for $246,300 was due on 14 July 2026. When will payment be made?\n\nTasha Green",
    ))
    response = await api.post(f"{API}/issues/{issue['id']}/draft", json={"writer": TASHA})
    assert response.status_code == 200, response.text
    draft = response.json()

    assert draft["recipient"]["audience"] == "customer"
    assert draft["recipient"]["role"] == "Billing contact at Northgate Independent School District"
    assert draft["recipient"]["email"] and "@" in draft["recipient"]["email"]
    assert (draft["subject"], draft["warnings"], draft["as_of"]) == ("Invoice INV-2026-0538, $246,300 past due", [], "2026-07-28")

    # The model was given the facts and no tools, and told it is writing to someone outside.
    request = scripted.requests[0]
    assert request["tools"] == []
    brief = json.loads(request["input"][0]["content"])
    assert brief["writer"] == TASHA and brief["recipient"]["name"] == draft["recipient"]["name"]
    assert (brief["facts"]["document"], brief["facts"]["amount"], brief["facts"]["days_late"]) == ("INV-2026-0538", "246300.00", 14)
    assert brief["facts"]["records"][0]["unpaid"] == "246300.00"
    assert "outside the company" in request["instructions"] and "28 July 2026" in request["instructions"]


async def test_a_draft_with_a_figure_that_is_not_in_the_records_is_sent_back_then_flagged(api, model):
    issue = await issue_about(api, "INV-2026-0538")
    wrong = drafted("Invoice INV-2026-0538", "Invoice INV-2026-0538 for $250,000 is past due, plus a $500 late fee.")
    right = drafted("Invoice INV-2026-0538", "Invoice INV-2026-0538 for $246,300 is past due.")

    scripted = model(wrong, right)
    fixed = (await api.post(f"{API}/issues/{issue['id']}/draft", json={"writer": TASHA})).json()
    assert fixed["warnings"] == [] and "$246,300" in fixed["body"]
    assert "$250,000 is not a figure from the records" in scripted.requests[-1]["input"][-1]["content"]

    # Still wrong after one correction: it comes back, with what to check spelled out.
    model(wrong)
    flagged = (await api.post(f"{API}/issues/{issue['id']}/draft", json={"writer": TASHA})).json()
    assert flagged["warnings"] == ["$250,000 is not a figure from the records", "$500 is not a figure from the records"]

    model(drafted("Past due invoice", "Dear [Name], your invoice is past due."))
    vague = (await api.post(f"{API}/issues/{issue['id']}/draft", json={"writer": TASHA})).json()
    assert vague["warnings"] == [
        "INV-2026-0538 is not named in the message", "A placeholder in brackets was left in the message",
    ]


async def test_other_follow_ups_stay_inside_the_company(api, model):
    issue = await issue_about(api, "ARS-20447")  # an early-pay discount on one of Tasha's jobs
    body = "Bill ARS-20447 for $48,350 needs approving before the discount deadline."

    model(drafted("Bill ARS-20447", body))
    from_owner = (await api.post(f"{API}/issues/{issue['id']}/draft", json={"writer": TASHA})).json()
    assert from_owner["recipient"] == {
        "audience": "internal", "name": "Finance", "role": "Harborstone's finance team", "email": None, "cc": [],
    }

    scripted = model(drafted("Bill ARS-20447", body))
    from_finance = (await api.post(f"{API}/issues/{issue['id']}/draft", json={"writer": "Rachel Kim"})).json()
    assert from_finance["recipient"] == {
        "audience": "internal", "name": TASHA, "role": "Has this issue as the job's ops manager",
        "email": "tasha.green@ciridae.com", "cc": [],
    }
    assert "colleague at Harborstone" in scripted.requests[0]["instructions"]


async def test_drafting_needs_a_key_an_open_issue_and_an_issue_that_exists(api, model, monkeypatch):
    issue = await issue_about(api, "INV-2026-0538")
    assert (await api.post(f"{API}/issues/999999/draft", json={"writer": TASHA})).status_code == 404
    assert (await api.post(f"{API}/issues/{issue['id']}/draft", json={})).status_code == 422

    monkeypatch.setattr(database.settings, "openai_api_key", "")
    refused = await api.post(f"{API}/issues/{issue['id']}/draft", json={"writer": TASHA})
    assert (refused.status_code, refused.json()["error"]["type"]) == (503, "ask_not_configured")


def coded(**reply) -> ResponseOutputMessage:
    """The bill coder handing back its answer."""
    body = {"job_number": None, "runner_up_job_number": None, "reasons": ["A line names the site."], **reply}
    return ResponseOutputMessage(
        id="msg_1", role="assistant", status="completed", type="message",
        content=[ResponseOutputText(annotations=[], text=json.dumps(body), type="output_text")],
    )


async def test_the_bill_coder_never_sees_which_job_a_bill_is_on(recon, db, model):
    """A bill whose job is known is put to the agent with that job hidden everywhere it
    could look. That is what lets the same code be scored against real answers."""
    from sqlalchemy import text

    bill_id, actual = (
        await db.execute(text(
            "select l.id, j.job_number from recon.money_line l join recon.job j on j.id = l.job_id "
            "where l.doc_number = 'LSR-88467'"
        ))
    ).one()
    scripted = model(
        call("the_bill"), call("vendor_history"), call("candidate_jobs"), call("job_work", job_number=actual),
        coded(decision="job", job_number=actual, confidence="high", reasons=["The email subject names Pier 12."]),
    )
    suggestion = await recon.suggest_job(bill_id)

    bill, history, jobs, work = (json.loads(result) for result in scripted.tool_results())
    assert bill == {
        "number": "LSR-88467", "vendor": "Lone Star Equipment Rental", "dated": "2026-07-17", "amount": "18930.00",
        "lines": bill["lines"], "email_subject": "Invoice LSR-88467 — Pier 12 generator rental",
    }
    assert {line["description"] for line in bill["lines"]} == {"Generator 150kVA rental — 3 weeks", "Fuel service"}
    assert "LSR-88467" not in json.dumps(history) + json.dumps(work)
    assert [(h["number"], h["job_number"]) for h in history] == [("LSR-88412", "CTX00080002")]
    assert len(jobs) == 25 and all("ops_manager" not in job for job in jobs)
    assert work["cost_entries"] and "amount" in work["cost_entries"][0]

    assert (suggestion.decision, suggestion.job_number, suggestion.confidence) == ("job", actual, "high")
    assert suggestion.job_name == "Gulf Coast — Pier 12 Flood Mitigation"
    assert [step.tool for step in suggestion.looked_at] == ["the_bill", "vendor_history", "candidate_jobs", "job_work"]
    assert scripted.requests[0]["tools"] == ["the_bill", "vendor_history", "candidate_jobs", "job_work"]


async def test_a_suggestion_is_recorded_on_the_issue_and_changes_nothing_else(api, db, model):
    from sqlalchemy import text

    issues = (await api.get(f"{API}/issues", params={"type": "no_job", "limit": 100})).json()["data"]
    issue = next(i for i in issues if i["document"] == "DTL-10012")

    model(call("the_bill"), coded(decision="job", job_number="MTX00100002", confidence="high", reasons=["A line names Bayou City Tower."]))
    response = await api.post(f"{API}/issues/{issue['id']}/coding")
    assert response.status_code == 200, response.text
    suggestion = response.json()
    assert (suggestion["bill"], suggestion["job_number"], suggestion["job_name"]) == (
        "DTL-10012", "MTX00100002", "Bayou City — Floor 14 Moisture Remediation",
    )

    after = (await api.get(f"{API}/issues/{issue['id']}")).json()
    assert after["status"] == "open"
    assert (after["events"][-1]["kind"], after["events"][-1]["actor"]) == ("suggested", "assistant")
    assert after["events"][-1]["note"] == (
        "Suggested job MTX00100002 (Bayou City — Floor 14 Moisture Remediation), high confidence. A line names Bayou City Tower."
    )
    # The bill itself is untouched: it still has no job.
    assert await db.scalar(text("select job_id from recon.money_line where doc_number = 'DTL-10012'")) is None


async def test_the_bill_coder_says_when_it_is_not_sure(api, model):
    issues = (await api.get(f"{API}/issues", params={"type": "no_job", "limit": 100})).json()["data"]
    path = f"{API}/issues/{next(i for i in issues if i['document'] == 'DTL-9954')['id']}/coding"

    model(coded(decision="not_a_job_cost", confidence="high", reasons=["The line is for branch offices."]))
    overhead = (await api.post(path)).json()
    assert (overhead["decision"], overhead["job_number"], overhead["runner_up"]) == ("not_a_job_cost", None, None)

    # A job named with low confidence is a guess. It is shown as the closest fit, not as the answer.
    model(coded(decision="job", job_number="MTX00040002", confidence="low"))
    guess = (await api.post(path)).json()
    assert (guess["decision"], guess["job_number"]) == ("unsure", None)
    assert guess["runner_up"] == {"job_number": "MTX00040002", "job_name": "Caprock — Imaging Suite Mold Remediation"}

    # A job that was never among the candidates is made up, and is refused outright.
    model(coded(decision="job", job_number="ZZZ99999999", confidence="high"))
    assert (await api.post(path)).status_code == 502
    model(coded(decision="job", confidence="high"))
    assert (await api.post(path)).status_code == 502

    # Only an unassigned bill can be coded.
    other = (await api.get(f"{API}/issues", params={"type": "past_due", "limit": 1})).json()["data"][0]
    assert (await api.post(f"{API}/issues/{other['id']}/coding")).status_code == 400


def test_the_scoring_counts_declining_to_guess_separately():
    from evals.bill_coding import summary, verdict

    assert verdict("job", "A", "A") == "right"
    assert verdict("job", "B", "A") == "wrong"
    assert verdict("not_a_job_cost", None, "A") == "wrong"
    assert verdict("not_a_job_cost", None, None) == "right"
    assert verdict("unsure", None, "A") == "unsure"
    rows = [
        {"verdict": "right", "confidence": "high"}, {"verdict": "right", "confidence": "medium"},
        {"verdict": "wrong", "confidence": "high"}, {"verdict": "unsure", "confidence": "low"},
    ]
    assert summary(rows) == {
        "bills": 4, "right": 2, "wrong": 1, "unsure": 1, "accuracy_when_it_answered": 0.667, "wrong_and_confident": 1,
    }


async def test_provider_problems_are_reported_as_what_they_are(recon, api, model, monkeypatch):
    """A refused key or an empty account is a setup problem, not a bad question."""
    import httpx
    from openai import AuthenticationError, RateLimitError

    from app.core.errors import AskProviderError

    def refusal(error_class, status, message):
        response = httpx.Response(status, request=httpx.Request("POST", "https://api.openai.com/v1/responses"))

        async def refuse(*args, **kwargs):
            raise error_class(f"Error code: {status}", response=response, body={"message": message})

        return refuse

    scripted = model(say("unused"))
    monkeypatch.setattr(scripted, "get_response", refusal(RateLimitError, 429, "You have no credits remaining."))
    with pytest.raises(AskProviderError, match="You have no credits remaining"):
        await recon.ask(AskRequest(question="How much are we owed?"))
    over_http = await api.post(f"{API}/ask", json={"question": "How much are we owed?"})
    assert over_http.status_code == 503
    assert over_http.json()["error"]["type"] == "ask_provider_refused"

    monkeypatch.setattr(scripted, "get_response", refusal(AuthenticationError, 401, "Incorrect API key provided."))
    with pytest.raises(AskProviderError, match="rejected the API key"):
        await recon.ask(AskRequest(question="How much are we owed?"))


async def test_ask_over_http(api, model):
    model(call("company_summary"), say("Customers owe $1,477,564, of which $719,004 is past due."))
    response = await api.post(f"{API}/ask", json={"question": "How much are we owed?"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answer"] == "Customers owe $1,477,564, of which $719,004 is past due."
    assert body["spec"]["elements"]["block-1"] == {"type": "Text", "props": {"text": body["answer"]}, "children": []}
    assert body["steps"] == [{"tool": "company_summary", "arguments": {}}]
    assert (body["sources"], body["worked_out"], body["as_of"]) == ([], [], "2026-07-28")
    assert (body["question"], body["asked_by"]) == ("How much are we owed?", "anonymous")

    history = (await api.get(f"{API}/ask/history", params={"asked_by": "anonymous"})).json()
    assert history[-1]["id"] == body["id"]
    assert (await api.delete(f"{API}/ask/history", params={"asked_by": "anonymous"})).status_code == 204
    assert (await api.get(f"{API}/ask/history", params={"asked_by": "anonymous"})).json() == []

    assert (await api.post(f"{API}/ask", json={"question": ""})).status_code == 422
    assert (await api.post(f"{API}/ask", json={"question": "x", "sql": "select 1"})).status_code == 422


async def test_customer_balances(api):
    response = await api.get(f"{API}/customer-balances", params={"limit": 100})
    balances = response.json()
    assert len(balances) == 12
    assert balances[0]["customer"] == "Northgate Independent School District"
    assert [b["owed"] for b in balances] == sorted((b["owed"] for b in balances), key=Decimal, reverse=True)
    assert sum(Decimal(b["owed"]) for b in balances) == Decimal("1477564.00")
    assert sum(Decimal(b["past_due"]) for b in balances) == Decimal("719004.00")

    mine = (await api.get(f"{API}/customer-balances", params={"owner": TASHA})).json()
    assert sum(Decimal(b["owed"]) for b in mine) == Decimal("639700.00")
