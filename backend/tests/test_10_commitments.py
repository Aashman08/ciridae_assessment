"""Commitments: promises and waits the assistant reads out of notes, and where each one stands."""

import json

import pytest
from openai.types.responses import ResponseOutputMessage, ResponseOutputText
from sqlalchemy import text
from test_07_ask import ScriptedModel, model  # noqa: F401  (the scripted stand-in for the model)
from test_08_items import reviewed

pytestmark = pytest.mark.usefixtures("synced")
API = "/api/v1"


def found(*commitments: dict) -> ResponseOutputMessage:
    """The model handing back what it found in a batch of notes."""
    body = {"commitments": [{"due_on": None, **c} for c in commitments]}
    return ResponseOutputMessage(
        id="msg_1", role="assistant", status="completed", type="message",
        content=[ResponseOutputText(annotations=[], text=json.dumps(body), type="output_text")],
    )


async def note_ids(db) -> dict[str, int]:
    """Each note's id, by the start of its text."""
    rows = await db.execute(text("select id, body from recon.note"))
    return {body.split()[0] + " " + body.split()[1]: note_id for note_id, body in rows}


async def get(api, path, **params):
    response = await api.get(f"{API}{path}", params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def test_reading_notes_needs_a_key_and_counts_what_is_unread(api):
    assert await get(api, "/notes/reading") == {"unread": 5, "read": 0}
    response = await api.post(f"{API}/notes/read")
    assert response.status_code == 503


async def test_only_checked_commitments_are_kept_and_a_note_is_read_once(api, db, model):  # noqa: F811
    notes = await note_ids(db)
    billing, voicemail = notes["Billing contact"], notes["Left voicemail"]
    dock, hood = notes["Dock leveler"], notes["Kitchen hood"]
    scripted = model(found(
        {"note_id": billing, "kind": "payment_promised", "who": "Redbird Industrial Trust", "what": "Pay INV-2026-0502", "due_on": "2026-07-31"},
        {"note_id": voicemail, "kind": "we_will", "who": "Tasha Green", "what": "Escalate to the property manager", "due_on": "2026-07-27"},
        {"note_id": dock, "kind": "promised_to_customer", "who": "Jenna Okafor", "what": "Weekly photo updates"},
        {"note_id": hood, "kind": "waiting_on", "who": "The health department", "what": "Walkthrough before close-out", "due_on": "2026-07-01"},
        # A note it was never shown: made up, so dropped.
        {"note_id": 999999, "kind": "we_will", "who": "Someone", "what": "Something"},
    ))
    response = await api.post(f"{API}/notes/read")
    assert response.status_code == 200, response.text
    assert response.json() == {"notes_read": 5, "commitments_found": 4}
    # Every note went to the model, with its date and the invoice it is on.
    sent = json.dumps(scripted.requests[0]["input"])
    assert "INV-2026-0502" in sent and "Dock leveler steel delivered" in sent

    # Read once: asking again sends nothing.
    assert await get(api, "/notes/reading") == {"unread": 0, "read": 5}
    again = await api.post(f"{API}/notes/read")
    assert again.json() == {"notes_read": 0, "commitments_found": 0} and len(scripted.requests) == 1

    listed = (await get(api, "/commitments"))["data"]
    by_what = {c["what"]: c for c in listed}
    # A date before the note was written cannot be its due date, so it is dropped.
    assert by_what["Walkthrough before close-out"]["due_on"] is None
    # The figures are as of 28 July: the 27 July escalation is missed, the 31 July payment due soon.
    assert by_what["Escalate to the property manager"]["state"] == "missed"
    assert by_what["Pay INV-2026-0502"]["state"] == "due_soon"
    assert by_what["Weekly photo updates"]["state"] == "open"
    assert [c["state"] for c in listed] == ["missed", "due_soon", "open", "open"]
    promise = by_what["Pay INV-2026-0502"]
    assert (promise["job_number"], promise["document"], promise["noted_by"], promise["noted_in"]) == (
        "CTX00080002", "INV-2026-0502", "Jenna Okafor", "accounting",
    )
    assert [c["what"] for c in (await get(api, "/commitments", job="CTX00080002"))["data"]] == ["Pay INV-2026-0502", "Weekly photo updates"]


async def test_a_missed_payment_promise_tags_its_invoice_and_reaches_the_review(api, db, model):  # noqa: F811
    await db.execute(text("update recon.commitment set due_on = '2026-07-27' where what = 'Pay INV-2026-0502'"))
    await db.commit()
    groups = (await api.get(f"{API}/items")).json()["groups"]
    unpaid = next(i for g in groups for i in g["items"] if i["key"] == "invoice_unpaid:INV-2026-0502")
    assert {"key": "promise_missed", "label": "Payment promised by 27 Jul, not received"} in unpaid["tags"]

    scripted = model(reviewed({"item_key": "invoice_unpaid:INV-2026-0502", "decision": "act", "reason": "The promised payment did not arrive."}))
    assert (await api.post(f"{API}/jobs/CTX00080002/review")).status_code == 200
    sent = json.dumps(scripted.requests[0]["input"])
    assert "Pay INV-2026-0502" in sent and "missed" in sent and "Weekly photo updates" in sent


async def test_a_payment_after_the_promise_keeps_it(api, db):
    # A payment on INV-2026-0502 dated after the note: the promise was kept.
    await db.execute(text("""
        insert into recon.money_line (kind, job_id, company_id, doc_number, description, amount, paid_amount, line_date,
                                      source_table, source_pk, source_record_id, sync_run_id)
        select 'customer_payment', job_id, company_id, doc_number, 'test', 1000, 0, date '2026-07-27',
               'test_payments', 'kept-promise', source_record_id, sync_run_id
        from recon.money_line where kind = 'customer_invoice' and doc_number = 'INV-2026-0502'
    """))
    await db.commit()
    kept = (await get(api, "/commitments", state="kept"))["data"]
    assert [c["what"] for c in kept] == ["Pay INV-2026-0502"]
    await db.execute(text("delete from recon.money_line where source_pk = 'kept-promise'"))
    await db.commit()


async def test_a_person_can_mark_one_done_and_it_is_in_the_log(api):
    open_ = (await get(api, "/commitments", kind="promised_to_customer"))["data"][0]
    done = await api.post(f"{API}/commitments/{open_['id']}/actions", json={"action": "done", "actor": "Ray Delgado"})
    assert done.status_code == 200 and done.json()["state"] == "done"
    assert (await api.post(f"{API}/commitments/{open_['id']}/actions", json={"action": "done", "actor": "Ray Delgado"})).status_code == 409

    log = (await get(api, "/activity", kind="commitment_done"))["data"]
    assert (log[0]["by"], log[0]["text"], log[0]["job_number"]) == ("Ray Delgado", "Weekly photo updates", "CTX00080002")

    reopened = await api.post(f"{API}/commitments/{open_['id']}/actions", json={"action": "reopen", "actor": "Ray Delgado"})
    assert reopened.json()["state"] == "open"
    assert (await api.post(f"{API}/commitments/424242/actions", json={"action": "done", "actor": "Ray"})).status_code == 404


def test_the_note_reading_eval_scores_misses_dates_and_extras():
    from datetime import date

    from evals.note_reading import score

    notes = {1: "Moisture readings…", 2: "Dock leveler…", 3: "Kitchen hood…", 4: "Billing contact…", 5: "Left voicemail…"}

    def c(note_id, kind, due=None):
        return {"note_id": note_id, "kind": kind, "who": "x", "what": "y", "due_on": date.fromisoformat(due) if due else None}

    perfect = [
        c(1, "we_will", "2026-07-31"), c(2, "promised_to_customer"), c(2, "we_will", "2026-07-27"), c(3, "waiting_on"),
        c(4, "payment_promised"), c(4, "we_will", "2026-07-31"), c(5, "we_will", "2026-07-27"),
    ]
    assert score(perfect, notes)["summary"] == {"expected": 6, "right": 6, "wrong date": 0, "missed": 0, "extras": 0}

    sloppy = [c(1, "we_will", "2026-08-07"), c(3, "waiting_on"), c(3, "we_will"), c(5, "we_will", "2026-07-27")]
    assert score(sloppy, notes)["summary"] == {"expected": 6, "right": 2, "wrong date": 1, "missed": 3, "extras": 1}
