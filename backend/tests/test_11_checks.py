"""Checks people add: written in their words, run on every sync like the built-in ones,
and their findings handled exactly like everyone else's."""

import json

import pytest
from openai.types.responses import ResponseOutputMessage, ResponseOutputText
from sqlalchemy import text
from test_07_ask import ScriptedModel, model  # noqa: F401  (the scripted stand-in for the model)

pytestmark = pytest.mark.usefixtures("synced")
API = "/api/v1"

BIG_SENT = {
    "match": "all",
    "conditions": [
        {"field": "open_amount", "op": ">", "value": 100000, "other_field": None, "times": None},
        {"field": "status", "op": "=", "value": "SENT", "other_field": None, "times": None},
    ],
    "amount_field": "open_amount",
}


def reply(body: dict) -> ResponseOutputMessage:
    return ResponseOutputMessage(
        id="msg_1", role="assistant", status="completed", type="message",
        content=[ResponseOutputText(annotations=[], text=json.dumps(body), type="output_text")],
    )


def wrote(approach: str, rule: dict | None = None, subject: str = "customer_invoice", title: str = "Large invoice still open", reason: str = "It can be tested on the fields.") -> ResponseOutputMessage:
    return reply({
        "title": title, "subject": subject, "about": "cash", "severity": "high",
        "approach": approach, "rule": rule, "reason": reason,
    })


def flagged(*flags: dict) -> ResponseOutputMessage:
    return reply({"flagged": list(flags)})


async def items(api) -> list[dict]:
    return [i for g in (await api.get(f"{API}/items")).json()["groups"] for i in g["items"]]


async def test_a_description_becomes_a_rule_that_is_tried_before_it_is_saved(api, db, model):  # noqa: F811
    model(wrote("rule", BIG_SENT))
    response = await api.post(f"{API}/checks/draft", json={"words": "Sent invoices with more than $100k still open"})
    assert response.status_code == 200, response.text
    draft = response.json()
    # The assistant names the check and works out what it looks at; the person only wrote one sentence.
    assert (draft["title"], draft["subject"], draft["about"], draft["severity"]) == ("Large invoice still open", "customer_invoice", "cash", "high")
    assert draft["approach"] == "rule"
    assert draft["reads_as"] == "Flags a customer invoice where open amount is more than $100,000 and status is sent"
    expected = await db.scalar(text(
        "select count(*) from recon.money_line where kind = 'customer_invoice' and status = 'SENT' and amount - paid_amount > 100000"
    ))
    assert len(draft["would_flag"]) == expected == 4
    assert draft["would_flag"][0]["subject"] == "INV-2026-0538" and draft["would_flag"][0]["amount"] == "246300.00"
    # Nothing is saved by trying.
    assert await db.scalar(text("select count(*) from recon.issue_type where origin != 'built_in'")) == 0


async def test_a_rule_naming_a_field_that_does_not_exist_is_refused(api, model):  # noqa: F811
    model(wrote("rule", {**BIG_SENT, "conditions": [{"field": "profit_vibes", "op": ">", "value": 1, "other_field": None, "times": None}]}, subject="job"))
    response = await api.post(f"{API}/checks/draft", json={"words": "Jobs that feel unprofitable"})
    assert response.status_code == 400 and "profit_vibes" in response.json()["error"]["message"]


async def test_a_saved_rule_runs_now_and_on_every_sync_like_a_built_in_check(api, db):
    created = await api.post(f"{API}/checks", json={
        "title": "Large invoice still open", "words": "Sent invoices with more than $100k still open",
        "subject": "customer_invoice", "approach": "rule", "rule": BIG_SENT, "about": "cash", "severity": "high", "actor": "Rachel Kim",
    })
    assert created.status_code == 201, created.text
    check = created.json()
    assert (check["origin"], check["created_by"], check["open_count"]) == ("rule", "Rachel Kim", 4)
    assert check["description"].startswith("Flags a customer invoice where open amount is more than $100,000")

    # Its findings are items like any other: a title, an owner, a next step, the record behind it.
    mine = [i for i in await items(api) if i["kind"] == "flagged"]
    assert {i["document"] for i in mine} == {"INV-2026-0515", "INV-2026-0526", "INV-2026-0538", "INV-2026-0578"}
    one = next(i for i in mine if i["document"] == "INV-2026-0538")
    assert one["title"] == "Large invoice still open" and one["action"]["label"] == "Ask about it"
    assert one["amount"] == "246300.00" and one["evidence"][0]["doc_number"] == "INV-2026-0538"
    assert one["details"] == ["Open amount: $246,300. Status: sent."]

    # Who added it is in the audit log.
    log = (await api.get(f"{API}/activity", params={"kind": "setting_changed"})).json()["data"]
    assert log[0]["by"] == "Rachel Kim" and log[0]["text"].startswith("Added this check")

    # The next sync finds the same four, without a model anywhere.
    assert (await api.post(f"{API}/sync-runs", json={})).status_code in (200, 201)
    assert await db.scalar(text(f"select count(*) from recon.issue where type_key = '{check['key']}' and status = 'open'")) == 4

    # Switched off, its findings clear on the next sync, like a built-in check's.
    await api.patch(f"{API}/issue-types/{check['key']}", json={"enabled": False, "actor": "Rachel Kim"})
    await api.post(f"{API}/sync-runs", json={})
    assert await db.scalar(text(f"select count(*) from recon.issue where type_key = '{check['key']}' and status = 'open'")) == 0


async def test_a_job_rule_can_compare_one_field_with_a_share_of_another(api, db, model):  # noqa: F811
    model(wrote("rule", {
        "match": "all",
        "conditions": [
            {"field": "ops_cost", "op": ">", "value": None, "other_field": "budget", "times": 0.9},
            {"field": "stage", "op": "=", "value": "IN_PROGRESS", "other_field": None, "times": None},
        ],
        "amount_field": "ops_cost",
    }, subject="job", title="Most of the budget used"))
    draft = (await api.post(f"{API}/checks/draft", json={"words": "Jobs in progress that have used 90% of budget"})).json()
    expected = await db.scalar(text("""
        select count(*) from recon.job j join recon.job_financials f on f.job_id = j.id
        and f.sync_run_id = (select max(id) from recon.sync_run where status = 'succeeded')
        where j.stage = 'IN_PROGRESS' and f.ops_cost > j.budget * 0.9
    """))
    assert draft["reads_as"] == "Flags a job where cost logged by the project team is more than 90% of budget and stage is in progress"
    assert len(draft["would_flag"]) == expected > 0


async def test_a_reading_check_keeps_only_findings_that_quote_the_notes(api, db, model):  # noqa: F811
    scripted = model(flagged(
        {"subject": "CTX00080002", "quote": "customer asked for weekly photo updates", "reason": "The customer has asked for something ongoing."},
        # Words that are not in its notes: dropped.
        {"subject": "BTX00070002", "quote": "the customer is furious", "reason": "Made up."},
        # A job it was never shown: dropped.
        {"subject": "ZZZ00000000", "quote": "anything", "reason": "Made up."},
    ))
    created = await api.post(f"{API}/checks", json={
        "title": "Customer asked for something extra", "words": "The customer has asked for something beyond the contract",
        "subject": "job", "approach": "reading", "about": "billing", "actor": "Tasha Green",
    })
    assert created.status_code == 201, created.text
    check = created.json()
    assert (check["origin"], check["open_count"]) == ("reading", 1)

    found = next(i for i in await items(api) if i["kind"] == "flagged" and i["title"] == "Customer asked for something extra")
    assert found["job_number"] == "CTX00080002" and found["document"] is None
    assert "customer asked for weekly photo updates" in found["details"][0]

    # A sync keeps the finding without calling the model.
    calls = len(scripted.requests)
    await api.post(f"{API}/sync-runs", json={})
    assert len(scripted.requests) == calls
    assert await db.scalar(text(f"select count(*) from recon.issue where type_key = '{check['key']}' and status = 'open'")) == 1

    # Reading again sends nothing when no note has changed.
    again = await api.post(f"{API}/checks/read")
    assert again.json()["notes_read"] == 0 and len(scripted.requests) == calls

    # A changed note is read again, and only that one.
    await db.execute(text("update recon.note set body = body || ' Customer also wants a second crane.' where body like 'Dock leveler%'"))
    await db.commit()
    model(flagged())
    reread = await api.post(f"{API}/checks/read")
    assert reread.json()["notes_read"] == 1
    assert await db.scalar(text(f"select count(*) from recon.issue where type_key = '{check['key']}' and status = 'open'")) == 0


async def test_the_writer_is_shown_every_kind_of_record_with_the_values_in_the_data(api, model):  # noqa: F811
    scripted = model(wrote("cannot", reason="Not something the records show."))
    await api.post(f"{API}/checks/draft", json={"words": "Anything at all worth a look"})
    brief = json.loads(scripted.requests[0]["input"][0]["content"])
    assert set(brief["fields_by_subject"]) == {"job", "customer_invoice", "vendor_bill", "customer", "vendor"}
    job_fields = {f["field"]: f for f in brief["fields_by_subject"]["job"]}
    assert {"ledger_margin_pct", "days_since_last_work", "open_issue_count", "customer", "branch"} <= set(job_fields)
    # Text fields come with the values they hold today, so a rule uses ones that exist.
    assert "IN_PROGRESS" in job_fields["stage"]["values_today"]
    assert "Rachel Kim" not in job_fields["ops_manager"].get("values_today", []) and job_fields["ops_manager"]["values_today"]


async def test_a_customer_check_adds_up_across_their_invoices(api, model):  # noqa: F811
    model(wrote("rule", {
        "match": "all",
        "conditions": [{"field": "owed", "op": ">", "value": 200000, "other_field": None, "times": None}],
        "amount_field": "owed",
    }, subject="customer", title="Customer owes a lot"))
    draft = (await api.post(f"{API}/checks/draft", json={"words": "Customers who owe us more than $200k"})).json()
    assert draft["reads_as"] == "Flags a customer where owed is more than $200,000"
    assert [(f["subject"], f["amount"]) for f in draft["would_flag"]] == [("Northgate Independent School District", "246300.00")]

    created = await api.post(f"{API}/checks", json={
        "title": "Customer owes a lot", "words": "Customers who owe us more than $200k", "subject": "customer",
        "approach": "rule", "rule": draft["rule"], "about": "cash", "actor": "Rachel Kim",
    })
    assert created.json()["open_count"] == 1
    # It is about a customer, not a job, so its item names the customer and sits with the ones on no job.
    item = next(i for i in await items(api) if i["title"] == "Customer owes a lot")
    assert (item["job_number"], item["company"], item["owner"]) == (None, "Northgate Independent School District", "Finance queue")


async def test_a_rule_can_look_for_words_on_a_bills_lines(api, model):  # noqa: F811
    model(wrote("rule", {
        "match": "all",
        "conditions": [{"field": "lines_text", "op": "contains", "value": "scaffold", "other_field": None, "times": None}],
        "amount_field": "open_amount",
    }, subject="vendor_bill", title="Scaffold bills"))
    draft = (await api.post(f"{API}/checks/draft", json={"words": "Bills for scaffolding"})).json()
    assert draft["reads_as"] == "Flags a vendor bill where what it bills for mentions \u201cscaffold\u201d"
    assert sorted(f["subject"] for f in draft["would_flag"]) == ["APX-40766", "APX-40912"]


async def test_a_reading_check_on_bills_reads_the_email_each_came_on(api, model):  # noqa: F811
    scripted = model(
        wrote("reading", subject="vendor_bill", title="Vendor chasing payment"),
        flagged(
            {"subject": "APX-40766", "quote": "Past due reminder", "reason": "The vendor is chasing payment."},
            {"subject": "ARS-20447", "quote": "Final notice before collections", "reason": "Not in the email; dropped."},
        ),
    )
    draft = (await api.post(f"{API}/checks/draft", json={"words": "The vendor is chasing us for payment"})).json()
    assert draft["approach"] == "reading"
    assert [f["subject"] for f in draft["would_flag"]] == ["APX-40766"]
    # What it read for a bill: the email's subject and the bill's own lines.
    sent = json.dumps(scripted.requests[1]["input"])
    assert "Past due reminder" in sent and "Exterior scaffold" in sent


async def test_every_field_the_writer_is_shown_runs_against_the_data(recon):
    """Each field of each kind of record compiles to SQL and runs, so no rule the assistant
    could write fails on a sync."""
    from app.models import IssueType
    from app.rules import FIELDS, NUMBERS, run_rule
    from app.schemas import Rule

    run = await recon._current_run()
    for subject, fields in FIELDS.items():
        for name, f in fields.items():
            value = -1e9 if f.kind in NUMBERS else (True if f.kind == "bool" else "zzz-not-a-value")
            op = ">" if f.kind in NUMBERS else ("=" if f.kind == "bool" else "!=")
            rule = Rule(match="all", conditions=[{"field": name, "op": op, "value": value, "other_field": None, "times": None}], amount_field=None)
            probe = IssueType(key="probe", title="probe", subject=subject, origin="rule", rule=rule.model_dump())
            await run_rule(recon.db, run, probe, rule)
