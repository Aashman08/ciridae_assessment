"""Activity: notes from the source systems and everything done in this app, in one list."""

from datetime import datetime

import pytest

pytestmark = pytest.mark.usefixtures("synced")
API = "/api/v1"


async def activity(api, **params) -> dict:
    response = await api.get(f"{API}/activity", params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def test_notes_are_copied_in_at_each_sync(api):
    """Project notes keep their job; accounting notes keep their invoice and its job."""
    project = (await activity(api, source="project"))["data"]
    assert {(n["job_number"], n["by"]) for n in project} == {
        ("MTX00100002", "Priya Raman"), ("CTX00080002", "Jenna Okafor"), ("BTX00070002", "Tasha Green"),
    }
    assert all(n["kind"] == "note" and n["text"] and n["document"] is None for n in project)

    accounting = (await activity(api, source="accounting"))["data"]
    assert {n["document"] for n in accounting} == {"INV-2026-0502", "INV-2026-0455"}
    redbird = next(n for n in accounting if n["document"] == "INV-2026-0502")
    assert (redbird["job_number"], redbird["by"]) == ("CTX00080002", "Jenna Okafor")
    assert redbird["text"].startswith("Billing contact confirmed receipt")


async def test_a_job_shows_its_notes_and_what_happened_to_its_issues(api):
    feed = await activity(api, job="CTX00080002", limit=500)
    entries = feed["data"]
    assert feed["total"] == len(entries)
    assert {e["job_number"] for e in entries} == {"CTX00080002"}
    assert {e["source"] for e in entries} == {"project", "accounting", "app"}
    # Every issue on the job was found by the sync, and says which check found it.
    found = [e for e in entries if e["kind"] == "opened"]
    assert found and all(e["by"] == "system" and e["about"] for e in found)
    # Newest first.
    times = [datetime.fromisoformat(e["at"]) for e in entries]
    assert times == sorted(times, reverse=True)


async def test_what_a_person_does_is_in_the_log_with_who_and_what(api):
    groups = (await api.get(f"{API}/items")).json()["groups"]
    key = next(g for g in groups if g["job_number"] == "CTX00080002")["items"][0]["key"]
    response = await api.post(f"{API}/items/{key}/actions", json={"actor": "Rachel Kim", "action": "update", "note": "Called Ray about it."})
    assert response.status_code == 200, response.text

    mine = (await activity(api, person="rachel kim", kind="commented"))["data"]
    assert len(mine) == 1
    assert (mine[0]["by"], mine[0]["text"], mine[0]["job_number"], mine[0]["source"]) == (
        "Rachel Kim", "Called Ray about it.", "CTX00080002", "app",
    )


async def test_a_change_to_a_check_is_logged_once_with_who_made_it(api):
    before = (await activity(api, kind="setting_changed"))["total"]
    changed = await api.patch(f"{API}/issue-types/slow_start", json={"tolerance": "21", "actor": "Luis Ortega"})
    assert changed.status_code == 200, changed.text
    # Saving the same value again changes nothing, so nothing is logged.
    assert (await api.patch(f"{API}/issue-types/slow_start", json={"tolerance": "21", "actor": "Luis Ortega"})).status_code == 200

    log = await activity(api, kind="setting_changed")
    assert log["total"] == before + 1
    entry = log["data"][0]
    assert (entry["by"], entry["about"], entry["text"]) == ("Luis Ortega", "Slow to start", "Tolerance changed from 14 days to 21 days")
    assert entry["job_number"] is None

    await api.patch(f"{API}/issue-types/slow_start", json={"tolerance": "14", "actor": "Luis Ortega"})


async def test_owner_and_paging_narrow_the_list_in_the_database(api):
    tasha_jobs = {j["job_number"] for j in (await api.get(f"{API}/jobs", params={"owner": "Tasha Green", "limit": 100})).json()["data"]}
    theirs = await activity(api, owner="Tasha Green", limit=500)
    assert theirs["data"] and {e["job_number"] for e in theirs["data"]} <= tasha_jobs

    first = await activity(api, limit=5)
    second = await activity(api, limit=5, offset=5)
    assert len(first["data"]) == 5 and first["has_more"]
    assert first["total"] == second["total"]
    # Two pages of five are exactly the first ten, in the same order: the order is fixed even
    # when a sync writes many entries in the same instant.
    assert first["data"] + second["data"] == (await activity(api, limit=10))["data"]


async def test_people_only_leaves_out_what_syncs_did(api):
    everything = await activity(api, job="CTX00080002", limit=500)
    people = await activity(api, job="CTX00080002", people_only="true", limit=500)
    assert people["data"] and all(e["by"] != "system" for e in people["data"])
    assert people["total"] == sum(e["by"] != "system" for e in everything["data"])
