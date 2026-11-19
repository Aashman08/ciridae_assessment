"""HTTP behaviour: routes, filters, paging, errors and access."""

import pytest
from sqlalchemy import event

from app import database

pytestmark = pytest.mark.usefixtures("synced")
API = "/api/v1"
TASHA = "Tasha Green"


async def get(api, path, **params):
    response = await api.get(f"{API}{path}", params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def post(api, path, body=None):
    return await api.post(f"{API}{path}", json=body)


def assert_error(response, status, error_type, message_part):
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["type"] == error_type
    assert message_part in error["message"]
    assert error["request_id"] == response.headers["X-Request-ID"]


# --- Sync runs ---------------------------------------------------------------


async def test_sync_run_reports_what_it_did(api):
    response = await post(api, "/sync-runs")
    assert response.status_code == 201
    run = response.json()
    assert (run["status"], run["as_of"]) == ("succeeded", "2026-07-28")
    assert run["stats"]["land"]["tables"] == 42
    assert run["stats"]["normalize"]["jobs"] == 25
    assert run["stats"]["issues"]["found"] == 62
    assert (await get(api, f"/sync-runs/{run['id']}"))["id"] == run["id"]
    latest = await get(api, "/sync-runs", limit=1)
    assert latest["data"][0]["id"] == run["id"]
    assert latest["has_more"] is True


async def test_sync_run_accepts_an_as_of_date(api):
    run = (await post(api, "/sync-runs", {"as_of": "2026-07-01"})).json()
    assert run["as_of"] == "2026-07-01"
    assert (await get(api, "/summary"))["cash"]["past_due"] == "0.00"
    await post(api, "/sync-runs")
    assert (await get(api, "/summary"))["cash"]["past_due"] == "719004.00"


async def test_unknown_sync_run_is_404(api):
    assert_error(await api.get(f"{API}/sync-runs/999999"), 404, "not_found", "No sync run found with id 999999")


# --- Summary -----------------------------------------------------------------


async def test_summary_for_finance(api):
    body = await get(api, "/summary")
    assert (body["as_of"], body["job_count"]) == ("2026-07-28", 25)
    assert body["cash"] == {
        "owed": "1477564.00",
        "past_due": "719004.00",
        "invoices_not_sent": "369100.00",
        "invoices_not_sent_count": 5,
        "vendor_bills_unpaid": "423215.00",
        "vendor_bills_count": 18,
        "invoice_count": 21,
    }
    assert body["contract_to_cash"] == {
        "contract_value": "5151450.00",
        "earned": "3249200.00",
        "invoiced": "3174100.00",
        "sent": "2805000.00",
        "collected": "1696536.00",
    }
    assert (body["open_issue_count"], body["jobs_with_issues"]) == (62, 21)
    assert len(body["issues_by_type"]) == 13
    assert body["issues_by_type"][0] == {
        "type_key": "past_due", "title": "Customer invoice past due", "severity": "high",
        "count": 5, "amount": "719004.00",
    }


async def test_summary_for_one_ops_manager(api):
    body = await get(api, "/summary", owner=TASHA)
    assert body["job_count"] == 6
    assert body["cash"]["owed"] == "639700.00"
    assert body["cash"]["past_due"] == "419800.00"
    assert body["cash"]["invoices_not_sent"] == "34500.00"
    assert (body["cash"]["vendor_bills_unpaid"], body["cash"]["vendor_bills_count"]) == ("111950.00", 5)
    assert body["open_issue_count"] == 10


# --- Jobs --------------------------------------------------------------------


async def test_jobs_list_and_filters(api):
    everything = await get(api, "/jobs", limit=100)
    assert (everything["total"], everything["has_more"]) == (25, False)
    counts = [j["issue_count"] for j in everything["data"]]
    assert counts == sorted(counts, reverse=True)

    assert (await get(api, "/jobs", stage="closed"))["total"] == 6
    assert (await get(api, "/jobs", owner=TASHA))["total"] == 6
    assert (await get(api, "/jobs", branch="phoenix"))["total"] == 2
    assert (await get(api, "/jobs", has_issues=False))["total"] == 4

    page = await get(api, "/jobs", limit=5, offset=5)
    assert len(page["data"]) == 5
    assert page["has_more"] is True
    assert page["data"][0] == everything["data"][5]


async def test_job_row_carries_figures_from_each_system(api):
    jobs = (await get(api, "/jobs", limit=100))["data"]
    job = next(j for j in jobs if j["job_number"] == "BTX00030002")
    assert job["name"] == "TexStar — Ballroom Water Intrusion"
    assert job["customer"] == "TexStar Hospitality Partners"
    assert (job["ops_manager"], job["account_executive"]) == (None, "Danny Alvarez")
    assert (job["contract_value"], job["invoiced"], job["collected"], job["owed"]) == (
        "312400.00", "178100.00", "0.00", "178100.00",
    )
    assert (job["ops_cost"], job["ledger_cost"]) == ("141360.00", "129700.00")
    assert job["top_issue"]["type_key"] == "past_due"


async def test_job_detail_puts_revenue_and_cost_figures_side_by_side(api):
    job = await get(api, "/jobs/CTX00080002")
    assert [(o["basis"], o["amount"]) for o in job["revenue_options"]] == [
        ("ledger", "432500.00"), ("invoiced", "324800.00"), ("collected", "129900.00"),
    ]
    assert [(o["basis"], o["amount"]) for o in job["cost_options"]] == [
        ("ops_log", "327600.00"), ("ledger", "318500.00"), ("ledger_plus_unpaid_bills", "395180.00"),
    ]
    assert job["revenue_options"][0]["label"] == "Earned, per ledger"
    assert job["profit"] == {
        "revenue_basis": "ledger", "cost_basis": "ledger", "revenue": "432500.00", "cost": "318500.00",
        "profit": "114000.00", "margin_pct": "26.4", "planned_margin_pct": "26.00",
    }
    assert len(job["issues"]) == 4
    assert [i["doc_number"] for i in job["invoices"]] == ["INV-2026-0502", "INV-2026-0592"]
    assert sorted(b["doc_number"] for b in job["vendor_bills"]) == ["LSR-88412", "RBC-1156"]
    assert job["original_contract_value"] == "618700.00"


async def test_job_profit_follows_the_pair_chosen(api):
    job = await get(api, "/jobs/ctx00080002", revenue="collected", cost="ledger_plus_unpaid_bills")
    profit = job["profit"]
    assert (profit["revenue"], profit["cost"], profit["profit"]) == ("129900.00", "395180.00", "-265280.00")

    no_revenue = (await get(api, "/jobs/CTX00150002", revenue="ledger", cost="ops_log"))["profit"]
    assert (no_revenue["margin_pct"], no_revenue["profit"]) == (None, "-188240.00")


async def test_job_rejects_an_unknown_basis_or_number(api):
    assert (await api.get(f"{API}/jobs/CTX00080002", params={"cost": "guess"})).status_code == 422
    assert_error(await api.get(f"{API}/jobs/NOPE0001"), 404, "not_found", "No job found with number 'NOPE0001'")


async def test_job_lines_trace_to_source_records(api):
    lines = await get(api, "/jobs/CTX00080002/lines")
    assert {l["kind"] for l in lines} >= {"ops_cost", "ledger_cost", "ledger_revenue", "vendor_bill", "customer_invoice"}
    ops = await get(api, "/jobs/CTX00080002/lines", kind="ops_cost")
    assert sum(float(l["amount"]) for l in ops) == 327600

    bill = next(l for l in lines if l["doc_number"] == "RBC-1156")
    record = await get(api, f"/source-records/{bill['source_record_id']}")
    assert (record["system"], record["table_name"]) == ("accounting", "ap_invoices")
    assert record["payload"]["invoice_number"] == "RBC-1156"
    assert f"{record['payload']['amount']:.2f}" == bill["amount"] == "64200.00"


async def test_unknown_source_record_is_404(api):
    assert_error(await api.get(f"{API}/source-records/999999999"), 404, "not_found", "No source record found")


# --- Invoices and vendor bills -----------------------------------------------


async def test_invoices_and_bills_across_jobs(api):
    invoices = await get(api, "/lines", kind="customer_invoice", limit=100)
    assert invoices["total"] == 21
    assert (invoices["data"][0]["doc_number"], invoices["data"][0]["open_amount"]) == ("INV-2026-0538", "246300.00")

    assert (await get(api, "/lines", kind="vendor_bill", limit=100))["total"] == 18
    assert (await get(api, "/lines", kind="vendor_bill", no_job=True))["total"] == 3
    assert (await get(api, "/lines", kind="vendor_bill", owner=TASHA))["total"] == 5
    assert (await api.get(f"{API}/lines")).status_code == 422


# --- Issues ------------------------------------------------------------------


async def test_issues_list_and_filters(api):
    everything = await get(api, "/issues", limit=200)
    assert everything["total"] == 62
    amounts = [float(i["amount"]) for i in everything["data"]]
    assert amounts == sorted(amounts, reverse=True)
    assert everything["data"][0]["key"] == "past_due:INV-2026-0538"

    assert (await get(api, "/issues", owner=TASHA))["total"] == 10
    assert (await get(api, "/issues", type="not_sent"))["total"] == 5
    assert (await get(api, "/issues", job="CTX00080002"))["total"] == 4
    assert (await get(api, "/issues", severity="high"))["total"] == 22
    assert (await get(api, "/issues", status="resolved"))["total"] == 0
    assert (await api.get(f"{API}/issues", params={"colour": "red"})).status_code == 422


async def test_issue_detail_has_evidence_and_history(api):
    summary = (await get(api, "/issues", type="past_due"))["data"][0]
    issue = await get(api, f"/issues/{summary['id']}")
    assert issue["title"] == "Customer invoice past due"
    assert issue["job_name"] == "Northgate ISD — Admin Building Reroof"
    assert issue["owner"] == TASHA
    assert [(e["kind"], e["doc_number"], e["open_amount"]) for e in issue["evidence"]] == [
        ("customer_invoice", "INV-2026-0538", "246300.00")
    ]
    assert issue["events"][0]["kind"] == "opened"
    assert_error(await api.get(f"{API}/issues/999999"), 404, "not_found", "No issue found with id 999999")


async def test_issue_actions_change_state_and_leave_a_trail(api):
    issue = (await get(api, "/issues", type="no_job"))["data"][0]
    path = f"/issues/{issue['id']}/actions"

    assigned = (await post(api, path, {"action": "assign", "actor": "Rachel Kim", "assignee": "Jenna Okafor"})).json()
    assert (assigned["status"], assigned["owner"]) == ("assigned", "Jenna Okafor")

    await post(api, path, {"action": "comment", "actor": "Jenna Okafor", "note": "Asked the vendor which site this was for"})
    resolved = (await post(api, path, {"action": "resolve", "actor": "Jenna Okafor", "note": "Coded to overhead"})).json()
    assert (resolved["status"], resolved["resolution_note"]) == ("resolved", "Coded to overhead")
    assert [e["kind"] for e in resolved["events"]] == ["opened", "assigned", "commented", "resolved"]
    assert resolved["events"][-1]["actor"] == "Jenna Okafor"

    # Resolved issues leave the active queue and survive a re-sync.
    assert (await get(api, "/issues", type="no_job"))["total"] == 2
    await post(api, "/sync-runs")
    assert (await get(api, f"/issues/{issue['id']}"))["status"] == "resolved"

    reopened = (await post(api, path, {"action": "reopen", "actor": "Rachel Kim"})).json()
    assert reopened["status"] == "open"
    assert (await get(api, "/issues", type="no_job"))["total"] == 3


async def test_issue_actions_are_validated(api):
    issue = (await get(api, "/issues", type="no_owner"))["data"][0]
    path = f"/issues/{issue['id']}/actions"
    assert_error(await post(api, path, {"action": "resolve", "actor": "Rachel Kim"}), 400, "invalid_request", "needs a note")
    assert_error(await post(api, path, {"action": "reopen", "actor": "Rachel Kim"}), 409, "invalid_state", "Only a resolved or cleared")
    assert (await post(api, path, {"action": "delete", "actor": "Rachel Kim"})).status_code == 422
    assert (await post(api, path, {"action": "comment", "note": "x"})).status_code == 422
    assert (await get(api, f"/issues/{issue['id']}"))["status"] == "open"


# --- Issue types -------------------------------------------------------------


async def test_issue_types_list_with_counts(api):
    types = {t["key"]: t for t in await get(api, "/issue-types")}
    assert len(types) == 13
    assert (types["past_due"]["open_count"], types["past_due"]["open_amount"]) == (5, "719004.00")
    assert (types["cost_disagree"]["tolerance"], types["cost_disagree"]["tolerance_unit"]) == ("0.02", "ratio")
    assert types["no_owner"]["tolerance"] is None


async def test_changing_a_tolerance_takes_effect_on_the_next_sync(api):
    path = f"{API}/issue-types/cost_disagree"
    assert (await api.patch(path, json={"tolerance": "0.1"})).json()["tolerance"] == "0.1"
    assert (await get(api, "/issues", type="cost_disagree"))["total"] == 17  # not yet
    await post(api, "/sync-runs")
    assert (await get(api, "/issues", type="cost_disagree"))["total"] == 9
    await api.patch(path, json={"tolerance": "0.02"})
    await post(api, "/sync-runs")
    assert (await get(api, "/issues", type="cost_disagree"))["total"] == 17


async def test_issue_type_can_be_switched_off(api):
    path = f"{API}/issue-types/discount"
    assert (await api.patch(path, json={"enabled": False})).json()["enabled"] is False
    await post(api, "/sync-runs")
    assert (await get(api, "/issues", type="discount"))["total"] == 0
    await api.patch(path, json={"enabled": True})
    await post(api, "/sync-runs")
    assert (await get(api, "/issues", type="discount"))["total"] == 3


async def test_issue_type_patch_is_validated(api):
    assert_error(await api.patch(f"{API}/issue-types/nope", json={"enabled": False}), 404, "not_found", "'nope'")
    assert_error(
        await api.patch(f"{API}/issue-types/no_owner", json={"tolerance": "0.5"}), 400, "invalid_request", "no tolerance"
    )
    assert (await api.patch(f"{API}/issue-types/cost_disagree", json={"tolerance": "-1"})).status_code == 422


# --- Where the work happens --------------------------------------------------


async def test_filtering_sorting_and_paging_run_in_the_database(api):
    """The database filters, sorts and cuts the page. Python only gets the rows it returns."""
    statements: list[str] = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(" ".join(statement.split()))

    event.listen(database.engine.sync_engine, "before_cursor_execute", capture)
    try:
        issues = await get(api, "/issues", owner=TASHA, severity="high", limit=2, offset=1)
        jobs = await get(api, "/jobs", stage="in_progress", has_issues=True, limit=3)
    finally:
        event.remove(database.engine.sync_engine, "before_cursor_execute", capture)

    assert (len(issues["data"]), issues["total"], issues["has_more"]) == (2, 4, True)
    listing = next(s for s in statements if "FROM recon.issue" in s and "LIMIT" in s)
    assert "lower(recon.issue.owner) =" in listing
    assert "recon.issue_type.severity =" in listing
    assert "ORDER BY recon.issue.amount DESC, recon.issue.key" in listing
    assert "OFFSET" in listing

    assert (len(jobs["data"]), jobs["has_more"]) == (3, True)
    listing = next(s for s in statements if "FROM recon.job JOIN recon.job_financials" in s and "LIMIT" in s)
    assert "recon.job.stage =" in listing
    assert "ORDER BY (SELECT count(*)" in listing


# --- Access and errors -------------------------------------------------------


async def test_api_key_is_enforced_only_when_set(api, monkeypatch):
    assert (await api.get(f"{API}/jobs")).status_code == 200
    monkeypatch.setattr(database.settings, "api_key", "s3cret")
    assert_error(await api.get(f"{API}/jobs"), 401, "unauthorized", "X-API-Key")
    assert (await api.get(f"{API}/jobs", headers={"X-API-Key": "wrong"})).status_code == 401
    assert (await api.get(f"{API}/jobs", headers={"X-API-Key": "s3cret"})).status_code == 200
    assert (await api.get("/health")).status_code == 200


async def test_unexpected_failure_is_logged_and_hidden(api, monkeypatch):
    from app.client import ReconClient

    async def explode(self, *args, **kwargs):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(ReconClient, "list_issue_types", explode)
    response = await api.get(f"{API}/issue-types")
    assert_error(response, 500, "internal_error", "Quote the request ID")
    assert "secret internal detail" not in response.text


async def test_openapi_describes_every_route(api):
    paths = (await api.get("/openapi.json")).json()["paths"]
    assert {
        "/health", "/api/v1/sync-runs", "/api/v1/sync-runs/{run_id}", "/api/v1/summary", "/api/v1/jobs",
        "/api/v1/jobs/{job_number}", "/api/v1/jobs/{job_number}/lines", "/api/v1/lines", "/api/v1/issues",
        "/api/v1/issues/{issue_id}", "/api/v1/issues/{issue_id}/actions", "/api/v1/issue-types",
        "/api/v1/issue-types/{key}", "/api/v1/source-records/{record_id}",
    } == set(paths)
