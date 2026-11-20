"""Items: what a person fixes, built from the checks that fired, and what can be done to one."""

import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from openai.types.responses import ResponseOutputMessage, ResponseOutputText
from sqlalchemy import text
from test_07_ask import ScriptedModel, model  # noqa: F401  (the scripted stand-in for the model)

from app.items import working_days_from

pytestmark = pytest.mark.usefixtures("synced")
API = "/api/v1"
TASHA = "Tasha Green"
D = Decimal
# The date of the sync, which is the clock for everything about items.
AS_OF = date(2026, 7, 28)


async def groups(api, **params) -> list[dict]:
    response = await api.get(f"{API}/items", params=params)
    assert response.status_code == 200, response.text
    return response.json()["groups"]


async def item(api, key: str, **params) -> dict:
    return next(i for g in await groups(api, **params) for i in g["items"] if i["key"] == key)


async def act(api, key: str, **body) -> dict:
    response = await api.post(f"{API}/items/{key}/actions", json={"actor": "Rachel Kim", **body})
    assert response.status_code == 200, response.text
    return response.json()


def reviewed(*entries: dict, first: str | None = None, why: str | None = None) -> ResponseOutputMessage:
    """The model handing back its review of a job's items."""
    body = {"items": [{"wait_until": None, **entry} for entry in entries], "first_item_key": first, "why_first": why}
    return ResponseOutputMessage(
        id="msg_1", role="assistant", status="completed", type="message",
        content=[ResponseOutputText(annotations=[], text=json.dumps(body), type="output_text")],
    )


async def test_sixty_nine_check_hits_are_fifty_five_things_to_fix(api, db):
    listed = await groups(api)
    items = [i for g in listed for i in g["items"]]
    kinds: dict[str, int] = {}
    for found in items:
        kinds[found["kind"]] = kinds.get(found["kind"], 0) + 1
    assert kinds == {
        "invoice_unpaid": 5, "invoice_not_sent": 5, "bill_stuck": 8, "bill_no_job": 3,
        "cost_gap": 19, "billing_gap": 2, "no_ops_manager": 7,
        "late_start": 2, "stalled": 2, "budget_risk": 2,
    }
    # Every open issue is behind exactly the items it should be, and none is lost.
    behind = {issue_id for found in items for issue_id in found["issue_ids"]}
    assert len(behind) == await db.scalar(text("select count(*) from recon.issue where status in ('open', 'assigned')")) == 69
    assert len({found["key"] for found in items}) == len(items) == 55

    # One group per job, and bills with no job in a group of their own, listed first.
    assert listed[0]["job_number"] is None and [i["kind"] for i in listed[0]["items"]] == ["bill_no_job"] * 3
    assert len(listed) == 24 and len({g["job_number"] for g in listed}) == 24

    # Money is counted once: the same figure the summary gives for flagged documents.
    flagged = sum(D(g["flagged_amount"]) for g in listed)
    summary = (await api.get(f"{API}/summary")).json()
    assert flagged == D(summary["flagged_documents"]["amount"]) == D("1342269.00")


async def test_three_checks_on_one_bill_are_one_item_with_tags(api):
    """The case that prompted this: a failed, late bill dated in a closed month on a closed job."""
    bill = await item(api, "bill_stuck:APX-40766")
    assert (bill["title"], bill["document"], bill["company"], bill["amount"]) == (
        "Vendor bill unpaid", "APX-40766", "Apex Scaffolding", "19800.00",
    )
    assert [tag["label"] for tag in bill["tags"]] == ["Posting failed", "9 days late", "Closed month", "Job closed"]
    assert sorted(bill["checks"]) == ["bill_overdue", "closed_bills", "closed_month"]
    assert (bill["severity"], bill["days_late"], bill["due_on"]) == ("high", 9, "2026-07-19")
    assert len(bill["issue_ids"]) == 3 and len(bill["evidence"]) == 1
    # The closed job's check adds a tag. The bill's own checks say what is wrong.
    assert len(bill["details"]) == 2 and all("APX-40766" in detail for detail in bill["details"])

    job = next(g for g in await groups(api) if g["job_number"] == "CTX00030003")
    assert [i["kind"] for i in job["items"]] == ["bill_stuck", "cost_gap", "no_ops_manager"]
    assert [tag["label"] for tag in job["tags"]] == ["Bill unpaid", "Cost gap", "No ops manager"]
    # Three checks were found by the same sync. The item's history says so once.
    assert [event["kind"] for event in bill["events"]] == ["opened"]

    summary = (await api.get(f"{API}/summary")).json()
    assert (summary["open_issue_count"], summary["open_item_count"]) == (69, 55)
    assert (await api.get(f"{API}/summary", params={"owner": TASHA})).json()["open_item_count"] == 10
    assert (job["flagged_amount"], job["ops_manager"]) == ("19800.00", None)


async def test_the_work_that_fixes_an_item_follows_fixed_rules(api):
    work = {found["key"]: found["action"] for g in await groups(api) for found in g["items"]}
    assert work["invoice_unpaid:INV-2026-0538"] == {"key": "message_customer", "label": "Chase the customer"}
    assert work["invoice_not_sent:INV-2026-0592"] == {"key": "message_colleague", "label": "Get the invoice sent"}
    assert work["bill_stuck:ARS-20447"] == {"key": "message_colleague", "label": "Get the bill approved"}
    assert work["bill_stuck:APX-40766"] == {"key": "message_colleague", "label": "Raise it with finance"}
    assert work["bill_no_job:DTL-10012"] == {"key": "code_bill", "label": "Suggest a job"}
    assert work["cost_gap:CTX00030003"]["label"] == "Ask to reconcile costs"
    assert work["no_ops_manager:CTX00030003"] == {"key": "assign_ops_manager", "label": "Assign an ops manager"}

    # Until the assistant has reviewed a job, the suggestion is the rule, and the job starts with its most serious item.
    job = next(g for g in await groups(api) if g["job_number"] == "RTX00050002")
    assert job["reviewed_at"] is None
    assert job["suggestion"] == {
        "item_key": "invoice_unpaid:INV-2026-0538", "action": {"key": "message_customer", "label": "Chase the customer"},
        "reason": None, "by": "rule",
    }
    assert all(found["suggestion"]["by"] == "rule" for found in job["items"])


async def test_items_can_be_limited_to_a_person_a_state_or_a_check(api):
    mine = await groups(api, owner=TASHA)
    assert {i["owner"] for g in mine for i in g["items"]} == {TASHA}
    assert sum(len(g["items"]) for g in mine) == 10

    only = await groups(api, type="discount")
    assert len(only) == 3 and "RTX00050002" in {g["job_number"] for g in only}
    assert all(any("discount" in found["checks"] for found in g["items"]) for g in only)
    assert (await api.get(f"{API}/items", params={"state": "sideways"})).status_code == 422


async def test_an_action_on_an_item_reaches_every_check_behind_it(api, db):
    key = "bill_stuck:CVG-6540"
    before = await item(api, key)
    assert len(before["issue_ids"]) == 3 and before["state"] == "needs_action"

    # A note, a new owner and a date, saved together and recorded once.
    updated = await act(api, key, action="update", note="AP will re-post it Monday.", assignee=TASHA, follow_up_in_working_days=5)
    assert (updated["owner"], updated["owner_role"], updated["state"]) == (TASHA, "assigned", "waiting")
    assert updated["follow_up_on"] == str(working_days_from(AS_OF, 5))
    assert [event["kind"] for event in updated["events"][-3:]] == ["assigned", "follow_up", "commented"]
    assert updated["note_count"] == 1
    rows = (await db.execute(text(
        "select owner, status, follow_up_on from recon.issue where id = any(:ids)"), {"ids": before["issue_ids"]}
    )).all()
    assert {(row.owner, row.status, str(row.follow_up_on)) for row in rows} == {(TASHA, "assigned", updated["follow_up_on"])}

    # Waiting items are out of the needs-action list and in the waiting one.
    assert all(i["key"] != key for g in await groups(api, state="needs_action") for i in g["items"])
    assert (await item(api, key, state="waiting"))["state"] == "waiting"

    resolved = await act(api, key, action="resolve", note="Posted and paid.")
    assert (resolved["state"], resolved["resolution_note"], resolved["follow_up_on"]) == ("done", "Posted and paid.", None)
    assert await db.scalar(text("select count(*) from recon.issue where id = any(:ids) and status = 'resolved'"), {"ids": before["issue_ids"]}) == 3
    assert all(i["key"] != key for g in await groups(api) for i in g["items"])
    assert (await item(api, key, state="done"))["state"] == "done"

    reopened = await act(api, key, action="reopen")
    assert reopened["state"] == "needs_action"
    await act(api, key, action="update", assignee=before["owner"], clear_follow_up=True)

    assert (await api.post(f"{API}/items/{key}/actions", json={"actor": "Rachel Kim", "action": "reopen"})).status_code == 409
    assert (await api.post(f"{API}/items/bill_stuck:NOPE-1/actions", json={"actor": "Rachel Kim", "action": "resolve", "note": "x"})).status_code == 404
    assert (await api.post(f"{API}/items/nonsense/actions", json={"actor": "Rachel Kim", "action": "resolve", "note": "x"})).status_code == 404


async def test_a_dismissed_item_comes_back_only_if_the_amount_changes(api, recon, source):
    key = "cost_gap:MTX00010002"
    gap = await item(api, key)
    assert gap["amount"] == "1920.00"
    assert (await api.post(f"{API}/items/{key}/actions", json={"actor": "Rachel Kim", "action": "dismiss"})).status_code == 400

    dismissed = await act(api, key, action="dismiss", note="Timing. Equipment rental posts next month.")
    assert (dismissed["state"], dismissed["resolution_note"]) == ("done", "Expected: Timing. Equipment rental posts next month.")
    assert dismissed["events"][-1]["kind"] == "dismissed"

    # The same figure at the next sync: it stays dismissed.
    await recon.run_sync()
    assert (await item(api, key, state="done"))["state"] == "done"

    # A different figure is a new question, so it is back, and says why.
    await source.execute(text(
        "update source_company.actual_costs set amount = amount + 5000 where id = ("
        "  select c.id from source_company.actual_costs c join source_company.budgets b on b.id = c.budget_id"
        "  join source_company.opportunities o on o.id = coalesce(c.opportunity_id, b.opportunity_id)"
        "  where o.legacy_opportunity_number = 'MTX00010002' limit 1)"
    ))
    await source.commit()
    await recon.run_sync()
    back = await item(api, key)
    assert (back["state"], back["amount"]) == ("needs_action", "6920.00")
    assert back["events"][-1]["kind"] == "reopened" and "Dismissed as expected at $1,920" in back["events"][-1]["note"]


async def test_a_message_about_an_item_goes_to_whoever_it_is_waiting_on(api, model):  # noqa: F811
    from test_07_ask import drafted

    async def recipient(key: str, writer: str) -> dict:
        model(drafted("Subject", "Body with no figures."))
        response = await api.post(f"{API}/items/{key}/draft", json={"writer": writer})
        assert response.status_code == 200, response.text
        return response.json()["recipient"]

    # An unpaid invoice: the customer's billing contact, whoever is writing.
    assert (await recipient("invoice_unpaid:INV-2026-0538", TASHA))["audience"] == "customer"
    # A bill waiting on project approval: the ops manager, unless she is the one writing.
    assert (await recipient("bill_stuck:ARS-20447", "Rachel Kim"))["name"] == TASHA
    assert (await recipient("bill_stuck:ARS-20447", TASHA))["name"] == "Finance"
    # A bill that failed to post is finance's to fix: the project team writes to finance, finance to the project team.
    assert (await recipient("bill_stuck:CVG-6540", "Ray Delgado"))["name"] == "Finance"
    assert (await recipient("bill_stuck:CVG-6540", "Rachel Kim"))["name"] == "Ray Delgado"

    # The message is told the one thing to ask for, by rule.
    scripted = model(drafted("Subject", "Body."))
    await api.post(f"{API}/items/bill_stuck:APX-40766/draft", json={"writer": "Rachel Kim"})
    facts = json.loads(scripted.requests[0]["input"][0]["content"])["facts"]
    assert facts["what_to_ask_for"] == "Post bill APX-40766 again; it failed to post."
    assert facts["tags"] == ["Posting failed", "9 days late", "Closed month", "Job closed"]

    # Items fixed some other way have no message to draft.
    assert (await api.post(f"{API}/items/no_ops_manager:CTX00030003/draft", json={"writer": TASHA})).status_code == 400


async def test_a_review_says_act_wait_or_dismiss_and_which_to_start_with(api, model):  # noqa: F811
    job = "RTX00050002"
    invoice, bill, gap = "invoice_unpaid:INV-2026-0538", "bill_stuck:ARS-20447", f"cost_gap:{job}"
    friday = str(working_days_from(AS_OF, 3))
    scripted = model(reviewed(
        {"item_key": invoice, "decision": "wait", "wait_until": friday, "reason": "A note says payment is on their next check run."},
        {"item_key": bill, "decision": "act", "reason": "The discount ends on 30 July."},
        first=bill, why="The discount deadline is days away.",
    ))
    response = await api.post(f"{API}/jobs/{job}/review")
    assert response.status_code == 200, response.text
    group = response.json()

    by_key = {found["key"]: found["suggestion"] for found in group["items"]}
    assert by_key[invoice] == {
        "action": {"key": "wait", "label": f"Wait until {date.fromisoformat(friday).day} {date.fromisoformat(friday):%b}"},
        "reason": "A note says payment is on their next check run.", "follow_up_on": friday, "by": "assistant",
    }
    assert by_key[bill] == {
        "action": {"key": "message_colleague", "label": "Get the bill approved"},
        "reason": "The discount ends on 30 July.", "follow_up_on": None, "by": "assistant",
    }
    assert group["suggestion"] == {
        "item_key": bill, "action": {"key": "message_colleague", "label": "Get the bill approved"},
        "reason": "The discount deadline is days away.", "by": "assistant",
    }
    assert group["reviewed_at"]

    # The agent saw the items and their notes, has no tools, and was told today's date.
    request = scripted.requests[0]
    shown = json.loads(request["input"][0]["content"])
    assert request["tools"] == [] and {entry["item_key"] for entry in shown["items"]} == {invoice, bill}
    assert shown["items"][0]["work_that_fixes_it"] == "Chase the customer" and shown["job"]["name"].startswith("Northgate ISD")
    assert "Today is Tuesday 28 July 2026" in request["instructions"]

    # It is kept: the job and the list both show it without asking again.
    assert (await item(api, invoice))["suggestion"]["by"] == "assistant"
    detail = (await api.get(f"{API}/jobs/{job}")).json()
    assert detail["items"]["suggestion"]["item_key"] == bill

    # Until something it rested on changes. Then the rules stand in again.
    await act(api, invoice, action="update", note="They paid half.")
    assert (await item(api, invoice))["suggestion"]["by"] == "rule"
    assert (await api.get(f"{API}/jobs/{job}")).json()["items"]["reviewed_at"] is None
    assert gap not in by_key


async def test_a_review_cannot_wave_money_away_invent_an_item_or_pick_a_silly_date(api, model):  # noqa: F811
    job = "CTX00080002"
    unpaid, unsent, cost = "invoice_unpaid:INV-2026-0502", "invoice_not_sent:INV-2026-0592", f"cost_gap:{job}"
    model(reviewed(
        {"item_key": unpaid, "decision": "dismiss", "reason": "Small."},
        {"item_key": unsent, "decision": "wait", "wait_until": "1999-01-01", "reason": "Finance said next week."},
        {"item_key": cost, "decision": "dismiss", "reason": "The gap is under 3% of ledger cost."},
        first=unsent,
    ))
    group = (await api.post(f"{API}/jobs/{job}/review")).json()
    by_key = {found["key"]: found["suggestion"] for found in group["items"]}
    # An unpaid invoice is never dismissed on the assistant's say-so. It is acted on.
    assert by_key[unpaid]["action"]["key"] == "message_customer"
    # A date in the past becomes the standard five working days.
    assert by_key[unsent]["follow_up_on"] == str(working_days_from(AS_OF, 5))
    assert by_key[cost]["action"] == {"key": "dismiss", "label": "Dismiss as expected"}
    # An item that is to wait cannot also be the one to start with, so the rule picks.
    assert group["suggestion"]["by"] == "rule"

    model(reviewed({"item_key": "bill_stuck:MADE-UP", "decision": "act", "reason": "x"}))
    assert (await api.post(f"{API}/jobs/{job}/review")).status_code == 502
    assert (await api.post(f"{API}/jobs/CTX00010001/review")).status_code == 409  # nothing open on it
    assert (await api.post(f"{API}/jobs/NOPE/review")).status_code == 404


async def test_notes_already_in_accounting_reach_the_review_and_the_draft(api, model):  # noqa: F811
    """A promise someone recorded in accounting is the reason not to chase again. The agent has to be shown it."""
    from test_07_ask import drafted

    key = "invoice_unpaid:INV-2026-0502"
    note = {
        "by": "Jenna Okafor", "on": "2026-07-24",
        "note": "Billing contact confirmed receipt; payment scheduled on their next check run. Follow up Friday if remittance hasn't landed.",
    }
    assert (await item(api, key))["source_notes"] == [note]
    assert (await item(api, "invoice_unpaid:INV-2026-0538"))["source_notes"] == []

    scripted = model(reviewed({"item_key": key, "decision": "wait", "wait_until": "2026-07-31", "reason": "Payment is on their next check run."}))
    group = (await api.post(f"{API}/jobs/CTX00080002/review")).json()
    shown = json.loads(scripted.requests[0]["input"][0]["content"])
    about = next(entry for entry in shown["items"] if entry["item_key"] == key)
    assert about["notes"] == [{**note, "kind": "note in accounting"}]
    assert shown["job"]["project_notes"][0]["by"] == "Jenna Okafor" and "Dock leveler" in shown["job"]["project_notes"][0]["note"]
    waiting = next(found for found in group["items"] if found["key"] == key)["suggestion"]
    assert (waiting["action"]["label"], waiting["follow_up_on"]) == ("Wait until 31 Jul", "2026-07-31")

    scripted = model(drafted("Subject", "Body."))
    await api.post(f"{API}/items/{key}/draft", json={"writer": "Ray Delgado"})
    assert json.loads(scripted.requests[0]["input"][0]["content"])["facts"]["notes_so_far"][0] == note


def test_the_review_scoring_knows_the_one_promise_in_the_data():
    from evals.job_review import summary, verdict

    promised = "invoice_unpaid:INV-2026-0502"
    assert verdict("wait", "2026-07-31", promised, "invoice_unpaid") == "right"
    assert verdict("wait", "2026-08-04", promised, "invoice_unpaid") == "wrong date"
    assert verdict("act", None, promised, "invoice_unpaid") == "wrong"
    assert verdict("act", None, "invoice_unpaid:INV-2026-0538", "invoice_unpaid") == "right"
    assert verdict("wait", "2026-08-04", "invoice_unpaid:INV-2026-0538", "invoice_unpaid") == "wrong"
    assert verdict("dismiss", None, "cost_gap:CTX00080002", "cost_gap") == "right"
    assert verdict("wait", "2026-08-04", "cost_gap:CTX00080002", "cost_gap") == "wrong"
    rows = [{"item": promised, "verdict": "right"}, {"item": "x", "verdict": "wrong"}]
    assert summary(rows) == {"items": 2, "right": 1, "wrong": 1, "wrong date": 0, "accuracy": 0.5, "notes_read_correctly": "1 of 1"}


def test_working_days_skip_the_weekend():
    friday = date(2026, 11, 20)
    assert working_days_from(friday, 1) == date(2026, 11, 23)
    assert working_days_from(friday, 5) == friday + timedelta(days=7)


async def test_schedule_problems_are_found_and_named(api):
    """Money is half of it. The other half is whether jobs start, keep moving, and spend at the right pace."""
    items = {found["key"]: found for g in await groups(api) for found in g["items"]}

    # Won 23 July, not planned on site until 18 August: 26 days for planned work, against a 14-day tolerance.
    late = items["late_start:XTX00020001"]
    assert (late["title"], late["due_on"], late["severity"]) == ("Slow to start", "2026-08-18", "medium")
    assert [tag["label"] for tag in late["tags"]] == ["26 days from win to start", "Starts 18 Aug"]
    assert late["action"] == {"key": "message_colleague", "label": "Confirm the start"}
    # Planned work that starts within the tolerance is not flagged.
    assert "late_start:CTX00010001" not in items and "late_start:BTX00040001" not in items

    # Past its planned finish, and nothing logged for two weeks: one stalled job, two reasons.
    stalled = items["stalled:BTX00030002"]
    assert sorted(stalled["checks"]) == ["no_activity", "past_finish"]
    assert [tag["label"] for tag in stalled["tags"]] == ["16 days past finish", "No work logged for 14 days"]
    assert stalled["severity"] == "high" and stalled["action"]["label"] == "Ask for a status update"
    assert [tag["label"] for tag in items["stalled:RAZ00060002"]["tags"]] == ["No work logged for 16 days"]

    # Spending ahead of schedule shows before the money runs out, not after.
    ahead = items["budget_risk:CTX00080002"]
    assert [tag["label"] for tag in ahead["tags"]] == ["72% of budget used", "61% of time gone"]
    over = items["budget_risk:CTX00150002"]
    assert over["tags"][0]["label"] == "104% of budget used" and "already over budget" in over["details"][0]
    # A job that is on pace is not flagged, however much it has spent.
    assert "budget_risk:MTX00130002" not in items


async def test_urgent_jobs_follow_a_stated_rule_and_get_a_one_day_tolerance(api, db, recon):
    """The CRM's urgency field is empty, so urgency follows a fixed rule: mitigation, or a named catastrophe."""
    reasons = dict((await db.execute(text("select job_number, urgent_reason from recon.job where urgent_reason is not null"))).all())
    assert reasons["MTX00100002"] == "Mitigation is emergency response"
    assert reasons["RTX00010004"] == "Part of the North Texas Hail Event"
    # Six mitigation jobs, and two roofing jobs from the hail event. No planned construction work.
    assert len(reasons) == 8 and not any(number.startswith("C") for number in reasons)

    # An urgent job waiting two days to start is flagged; the same wait on planned work is not.
    await db.execute(text(
        "update recon.job set urgent_reason = 'Mitigation is emergency response', on_site_on = won_on + 2 "
        "where job_number = 'BTX00040001'"
    ))
    await db.commit()
    from app.issues import detect
    from app.models import SyncRun
    from sqlalchemy import select as sql_select

    run = await db.scalar(sql_select(SyncRun).order_by(SyncRun.id.desc()).limit(1))
    found = {f.key for f in await detect(db, run)}
    assert "slow_start:BTX00040001" in found
    await recon.run_sync()  # puts the job back as the source has it
    assert await db.scalar(text("select urgent_reason from recon.job where job_number = 'BTX00040001'")) is None


async def test_a_schedule_message_goes_to_the_ops_manager_or_from_them_to_the_account_executive(api, model):  # noqa: F811
    from test_07_ask import drafted

    async def recipient(key: str, writer: str) -> dict:
        model(drafted("Subject", "Body with no figures."))
        response = await api.post(f"{API}/items/{key}/draft", json={"writer": writer})
        assert response.status_code == 200, response.text
        return response.json()["recipient"]

    assert (await recipient("budget_risk:CTX00080002", "Luis Ortega"))["name"] == "Ray Delgado"
    from_manager = await recipient("budget_risk:CTX00080002", "Ray Delgado")
    assert from_manager["name"] == "Marcus Webb" and "keeps the customer informed" in from_manager["role"]

    scripted = model(drafted("Subject", "Body."))
    await api.post(f"{API}/items/late_start:XTX00020001/draft", json={"writer": "Luis Ortega"})
    facts = json.loads(scripted.requests[0]["input"][0]["content"])["facts"]
    assert facts["what_to_ask_for"].startswith("Confirm the date the crew will be on site")


async def test_a_days_tolerance_must_be_a_whole_number(api):
    path = f"{API}/issue-types/no_activity"
    assert (await api.patch(path, json={"tolerance": "2.5"})).status_code == 400
    assert (await api.patch(path, json={"tolerance": "0"})).status_code == 400
    assert (await api.patch(path, json={"tolerance": "21"})).json()["tolerance"] == "21"
    await api.patch(path, json={"tolerance": "14"})


async def test_the_operations_view_answers_start_speed_pace_and_ownership(api):
    response = await api.get(f"{API}/operations")
    assert response.status_code == 200, response.text
    ops = response.json()
    assert ops["start_tolerance_days"] == 14 and "empty on every record" in ops["urgent_rule"]

    # Every urgent job in the data was on site the day it was won. The view says so, job by job.
    urgent = {u["job_number"]: u for u in ops["urgent"]}
    assert len(urgent) == 8 and all(u["started_in_time"] for u in urgent.values())
    assert (urgent["MTX00100002"]["days_damage_to_site"], urgent["MTX00100002"]["days_win_to_site"]) == (2, 0)

    # Four jobs are won and waiting; two are slower to start than the tolerance allows.
    waiting = ops["waiting"]
    assert [(w["job_number"], w["days_win_to_start"], w["slow"]) for w in waiting] == [
        ("XTX00020001", 26, True), ("CTX00130001", 21, True), ("CTX00010001", 13, False), ("BTX00040001", 7, False),
    ]

    # Every job in progress, with its pace. The ones with something wrong come first.
    pace = {p["job_number"]: p for p in ops["in_progress"]}
    assert len(pace) == 10 and ops["in_progress"][0]["job_number"] == "BTX00030002"
    assert pace["BTX00030002"]["flags"] == ["no_activity", "past_finish"]
    assert (pace["CTX00080002"]["budget_used_pct"], pace["CTX00080002"]["time_gone_pct"]) == ("72.0", "61.3")
    assert pace["MTX00130002"]["flags"] == [] and pace["RAZ00060002"]["last_work_on"] == "2026-07-12"

    # Who owns what, and the jobs nobody owns.
    owners = {o["name"]: o for o in ops["owners"]}
    assert set(owners) == {"Ray Delgado", "Tasha Green", "None assigned"}
    assert ops["owners"][-1]["name"] == "None assigned"
    assert owners["Tasha Green"]["jobs_in_progress"] == 4 and owners["Tasha Green"]["jobs_not_started"] == 1
    total = sum(o["open_items"] for o in owners.values())
    assert total == 55 - 3  # every item, less the three bills that are on no job
