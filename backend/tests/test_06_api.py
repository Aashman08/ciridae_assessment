import pytest

API = "/api/v1"
TASHA = "Tasha Green"


@pytest.fixture(scope="module", autouse=True)
def synced(database):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        response = c.post(f"{API}/sync-runs")
        assert response.status_code == 201


def get(client, path, **params):
    response = client.get(f"{API}{path}", params=params)
    assert response.status_code == 200, response.text
    return response.json()


# --- Sync runs ---------------------------------------------------------------


def test_sync_run_reports_what_it_did(client):
    run = client.post(f"{API}/sync-runs").json()
    assert run["status"] == "succeeded"
    assert run["as_of"] == "2026-07-28"
    assert run["stats"]["land"]["tables"] == 42
    assert run["stats"]["normalize"]["jobs"] == 25
    assert run["stats"]["issues"]["found"] == 62
    assert get(client, f"/sync-runs/{run['id']}")["id"] == run["id"]
    assert get(client, "/sync-runs", limit=1)["items"][0]["id"] == run["id"]


def test_sync_run_accepts_an_as_of_date(client):
    run = client.post(f"{API}/sync-runs", json={"as_of": "2026-07-01"}).json()
    assert run["as_of"] == "2026-07-01"
    assert get(client, "/summary")["cash"]["past_due"] == 0
    client.post(f"{API}/sync-runs")
    assert get(client, "/summary")["cash"]["past_due"] == 719004


def test_unknown_sync_run_is_404(client):
    assert client.get(f"{API}/sync-runs/999999").status_code == 404


# --- Summary -----------------------------------------------------------------


def test_summary_for_finance(client):
    body = get(client, "/summary")
    assert body["as_of"] == "2026-07-28"
    assert body["job_count"] == 25
    assert body["cash"] == {
        "owed": 1477564,
        "past_due": 719004,
        "invoices_not_sent": 369100,
        "invoices_not_sent_count": 5,
        "vendor_bills_unpaid": 423215,
        "vendor_bills_count": 18,
    }
    assert body["contract_to_cash"] == {
        "contract_value": 5151450,
        "earned": 3249200,
        "invoiced": 3174100,
        "sent": 2805000,
        "collected": 1696536,
    }
    assert body["open_issue_count"] == 62
    assert body["jobs_with_issues"] == 21
    assert len(body["issues_by_type"]) == 13
    assert body["issues_by_type"][0] == {
        "type_key": "past_due", "title": "Customer invoice past due", "severity": "high", "count": 5, "amount": 719004,
    }


def test_summary_for_one_ops_manager(client):
    body = get(client, "/summary", owner=TASHA)
    assert body["job_count"] == 6
    assert body["cash"]["owed"] == 639700
    assert body["cash"]["past_due"] == 419800
    assert body["cash"]["invoices_not_sent"] == 34500
    assert body["cash"]["vendor_bills_unpaid"] == 111950
    assert body["cash"]["vendor_bills_count"] == 5
    assert body["open_issue_count"] == 10


# --- Jobs --------------------------------------------------------------------


def test_jobs_list_and_filters(client):
    everything = get(client, "/jobs", limit=100)
    assert everything["total"] == 25
    counts = [j["issue_count"] for j in everything["items"]]
    assert counts == sorted(counts, reverse=True)

    assert get(client, "/jobs", stage="closed")["total"] == 6
    assert get(client, "/jobs", owner=TASHA)["total"] == 6
    assert get(client, "/jobs", branch="phoenix")["total"] == 2
    assert get(client, "/jobs", has_issues=False)["total"] == 4

    page = get(client, "/jobs", limit=5, offset=5)
    assert len(page["items"]) == 5
    assert page["items"][0] == everything["items"][5]


def test_job_row_carries_figures_from_each_system(client):
    job = next(j for j in get(client, "/jobs", limit=100)["items"] if j["job_number"] == "BTX00030002")
    assert job["name"] == "TexStar — Ballroom Water Intrusion"
    assert job["customer"] == "TexStar Hospitality Partners"
    assert job["ops_manager"] is None
    assert job["account_executive"] == "Danny Alvarez"
    assert (job["contract_value"], job["invoiced"], job["collected"], job["owed"]) == (312400, 178100, 0, 178100)
    assert (job["ops_cost"], job["ledger_cost"]) == (141360, 129700)
    assert job["top_issue"]["type_key"] == "past_due"


def test_job_detail_puts_revenue_and_cost_figures_side_by_side(client):
    job = get(client, "/jobs/CTX00080002")
    assert [(o["basis"], o["amount"]) for o in job["revenue_options"]] == [
        ("ledger", 432500), ("invoiced", 324800), ("collected", 129900),
    ]
    assert [(o["basis"], o["amount"]) for o in job["cost_options"]] == [
        ("ops_log", 327600), ("ledger", 318500), ("ledger_plus_unpaid_bills", 395180),
    ]
    assert job["revenue_options"][0]["label"] == "Earned, per ledger"
    assert job["profit"] == {
        "revenue_basis": "ledger", "cost_basis": "ledger", "revenue": 432500, "cost": 318500,
        "profit": 114000, "margin_pct": 26.4, "planned_margin_pct": 26.0,
    }
    assert len(job["issues"]) == 4
    assert [i["doc_number"] for i in job["invoices"]] == ["INV-2026-0502", "INV-2026-0592"]
    assert sorted(b["doc_number"] for b in job["vendor_bills"]) == ["LSR-88412", "RBC-1156"]
    assert job["original_contract_value"] == 618700


def test_job_profit_follows_the_pair_chosen(client):
    profit = get(client, "/jobs/ctx00080002", revenue="collected", cost="ledger_plus_unpaid_bills")["profit"]
    assert (profit["revenue"], profit["cost"], profit["profit"]) == (129900, 395180, -265280)

    no_revenue = get(client, "/jobs/CTX00150002", revenue="ledger", cost="ops_log")["profit"]
    assert no_revenue["margin_pct"] is None
    assert no_revenue["profit"] == -188240


def test_job_rejects_an_unknown_basis_or_number(client):
    assert client.get(f"{API}/jobs/CTX00080002", params={"cost": "guess"}).status_code == 422
    assert client.get(f"{API}/jobs/NOPE0001").status_code == 404


def test_job_lines_trace_to_source_records(client):
    lines = get(client, "/jobs/CTX00080002/lines")
    assert {l["kind"] for l in lines} >= {"ops_cost", "ledger_cost", "ledger_revenue", "vendor_bill", "customer_invoice"}
    ops = get(client, "/jobs/CTX00080002/lines", kind="ops_cost")
    assert sum(l["amount"] for l in ops) == 327600

    bill = next(l for l in lines if l["doc_number"] == "RBC-1156")
    record = get(client, f"/source-records/{bill['source_record_id']}")
    assert record["system"] == "accounting"
    assert record["table_name"] == "ap_invoices"
    assert record["payload"]["invoice_number"] == "RBC-1156"
    assert float(record["payload"]["amount"]) == bill["amount"] == 64200


def test_unknown_source_record_is_404(client):
    assert client.get(f"{API}/source-records/999999999").status_code == 404


# --- Invoices and vendor bills -----------------------------------------------


def test_invoices_and_bills_across_jobs(client):
    invoices = get(client, "/lines", kind="customer_invoice", limit=100)
    assert invoices["total"] == 21
    assert invoices["items"][0]["doc_number"] == "INV-2026-0538"
    assert invoices["items"][0]["open_amount"] == 246300

    bills = get(client, "/lines", kind="vendor_bill", limit=100)
    assert bills["total"] == 18
    assert get(client, "/lines", kind="vendor_bill", no_job=True)["total"] == 3
    assert get(client, "/lines", kind="vendor_bill", owner=TASHA)["total"] == 5
    assert client.get(f"{API}/lines").status_code == 422


# --- Issues ------------------------------------------------------------------


def test_issues_list_and_filters(client):
    everything = get(client, "/issues", limit=200)
    assert everything["total"] == 62
    amounts = [i["amount"] for i in everything["items"]]
    assert amounts == sorted(amounts, reverse=True)
    assert everything["items"][0]["key"] == "past_due:INV-2026-0538"

    assert get(client, "/issues", owner=TASHA)["total"] == 10
    assert get(client, "/issues", type="not_sent")["total"] == 5
    assert get(client, "/issues", job="CTX00080002")["total"] == 4
    assert get(client, "/issues", severity="high")["total"] == 22
    assert get(client, "/issues", status="resolved")["total"] == 0


def test_issue_detail_has_evidence_and_history(client):
    summary = get(client, "/issues", type="past_due")["items"][0]
    issue = get(client, f"/issues/{summary['id']}")
    assert issue["title"] == "Customer invoice past due"
    assert issue["job_name"] == "Northgate ISD — Admin Building Reroof"
    assert issue["owner"] == TASHA
    assert issue["next_step"] == "Call the customer's payables contact and log the outcome."
    assert [(e["kind"], e["doc_number"], e["open_amount"]) for e in issue["evidence"]] == [
        ("customer_invoice", "INV-2026-0538", 246300)
    ]
    assert issue["events"][0]["kind"] == "opened"
    assert client.get(f"{API}/issues/999999").status_code == 404


def test_issue_actions_change_state_and_leave_a_trail(client):
    issue = get(client, "/issues", type="no_job")["items"][0]
    url = f"{API}/issues/{issue['id']}/actions"

    assigned = client.post(url, json={"action": "assign", "actor": "Rachel Kim", "assignee": "Jenna Okafor"}).json()
    assert (assigned["status"], assigned["owner"]) == ("assigned", "Jenna Okafor")

    client.post(url, json={"action": "comment", "actor": "Jenna Okafor", "note": "Asked the vendor which site this was for"})
    resolved = client.post(url, json={"action": "resolve", "actor": "Jenna Okafor", "note": "Coded to overhead"}).json()
    assert resolved["status"] == "resolved"
    assert resolved["resolution_note"] == "Coded to overhead"
    assert [e["kind"] for e in resolved["events"]][-3:] == ["assigned", "commented", "resolved"]
    assert resolved["events"][-1]["actor"] == "Jenna Okafor"

    # Resolved issues leave the active queue and survive a re-sync.
    assert get(client, "/issues", type="no_job")["total"] == 2
    client.post(f"{API}/sync-runs")
    assert get(client, f"/issues/{issue['id']}")["status"] == "resolved"

    reopened = client.post(url, json={"action": "reopen", "actor": "Rachel Kim"}).json()
    assert reopened["status"] == "open"
    assert get(client, "/issues", type="no_job")["total"] == 3


def test_issue_actions_are_validated(client):
    issue = get(client, "/issues", type="no_owner")["items"][0]
    url = f"{API}/issues/{issue['id']}/actions"
    missing_note = client.post(url, json={"action": "resolve", "actor": "Rachel Kim"})
    assert missing_note.status_code == 400
    assert "needs a note" in missing_note.json()["detail"]
    assert client.post(url, json={"action": "delete", "actor": "Rachel Kim"}).status_code == 422
    assert client.post(url, json={"action": "comment", "note": "x"}).status_code == 422
    assert get(client, f"/issues/{issue['id']}")["status"] == "open"


# --- Issue types -------------------------------------------------------------


def test_issue_types_list_with_counts(client):
    types = get(client, "/issue-types")
    assert len(types) == 13
    by_key = {t["key"]: t for t in types}
    assert (by_key["past_due"]["open_count"], by_key["past_due"]["open_amount"]) == (5, 719004)
    assert (by_key["cost_disagree"]["tolerance"], by_key["cost_disagree"]["tolerance_unit"]) == (0.02, "ratio")
    assert by_key["no_owner"]["tolerance"] is None


def test_changing_a_tolerance_takes_effect_on_the_next_sync(client):
    url = f"{API}/issue-types/cost_disagree"
    assert client.patch(url, json={"tolerance": 0.1}).json()["tolerance"] == 0.1
    assert get(client, "/issues", type="cost_disagree")["total"] == 17  # not yet
    client.post(f"{API}/sync-runs")
    assert get(client, "/issues", type="cost_disagree")["total"] == 9
    client.patch(url, json={"tolerance": 0.02})
    client.post(f"{API}/sync-runs")
    assert get(client, "/issues", type="cost_disagree")["total"] == 17


def test_issue_type_can_be_switched_off(client):
    url = f"{API}/issue-types/discount"
    assert client.patch(url, json={"enabled": False}).json()["enabled"] is False
    client.post(f"{API}/sync-runs")
    assert get(client, "/issues", type="discount")["total"] == 0
    client.patch(url, json={"enabled": True})
    client.post(f"{API}/sync-runs")
    assert get(client, "/issues", type="discount")["total"] == 3


def test_issue_type_patch_is_validated(client):
    assert client.patch(f"{API}/issue-types/nope", json={"enabled": False}).status_code == 404
    assert client.patch(f"{API}/issue-types/no_owner", json={"tolerance": 0.5}).status_code == 400
    assert client.patch(f"{API}/issue-types/cost_disagree", json={"tolerance": -1}).status_code == 422


# --- Access ------------------------------------------------------------------


def test_api_key_is_enforced_only_when_set(client, monkeypatch):
    from app.config import get_settings

    assert client.get(f"{API}/jobs").status_code == 200
    monkeypatch.setenv("API_KEY", "s3cret")
    get_settings.cache_clear()
    try:
        assert client.get(f"{API}/jobs").status_code == 401
        assert client.get(f"{API}/jobs", headers={"X-API-Key": "wrong"}).status_code == 401
        assert client.get(f"{API}/jobs", headers={"X-API-Key": "s3cret"}).status_code == 200
        assert client.get("/health").status_code == 200
    finally:
        monkeypatch.delenv("API_KEY")
        get_settings.cache_clear()


def test_openapi_describes_every_route(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert {
        "/api/v1/sync-runs", "/api/v1/sync-runs/{run_id}", "/api/v1/summary", "/api/v1/jobs",
        "/api/v1/jobs/{job_number}", "/api/v1/jobs/{job_number}/lines", "/api/v1/lines", "/api/v1/issues",
        "/api/v1/issues/{issue_id}", "/api/v1/issues/{issue_id}/actions", "/api/v1/issue-types",
        "/api/v1/issue-types/{key}", "/api/v1/source-records/{record_id}",
    } <= set(paths)
