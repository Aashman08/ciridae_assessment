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


def wrote(approach: str, rule: dict | None = None, subject: str = "customer_invoice", title: str = "Large invoice still open") -> ResponseOutputMessage:
    return reply({
        "title": title, "subject": subject, "about": "cash", "severity": "high",
        "approach": approach, "rule": rule, "reason": "It can be tested on the fields.",
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


async def test_a_reading_check_cannot_look_at_vendor_bills(api):
    response = await api.post(f"{API}/checks", json={
        "title": "Vendor says the bill is wrong", "words": "The vendor says the bill amount is wrong",
        "subject": "vendor_bill", "approach": "reading", "about": "cost", "actor": "Rachel Kim",
    })
    assert response.status_code == 400
