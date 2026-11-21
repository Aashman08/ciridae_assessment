"""Sync step 4: what the checks find, and how issues behave across syncs."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text

from app.core.errors import InvalidRequestError, InvalidStateError
from app.core.models import Issue, IssueEvent, IssueType
from app.core.schemas import IssueAction, IssueDetailResponse, IssueFilters, IssueTypeUpdate

pytestmark = pytest.mark.usefixtures("synced")
D = Decimal
ACTIVE = ("open", "assigned")

# What the export holds as of 28 July 2026: findings and dollars per issue type.
EXPECTED = {
    "past_due": (5, D("719004.00")),
    "not_sent": (5, D("369100.00")),
    "cost_disagree": (17, D("227005.00")),
    "no_ledger_cost": (2, D("197140.00")),
    "closed_bills": (6, D("187190.00")),
    "closed_month": (1, D("19800.00")),
    "bill_overdue": (5, D("172810.00")),
    "rev_invoiced": (2, D("127600.00")),
    "discount": (3, D("72370.00")),
    "underbilled": (1, D("19900.00")),
    "over_contract": (1, D("14040.00")),
    "no_job": (3, D("8985.00")),
    "no_owner": (7, D("0.00")),
    # Schedule: whether jobs start on time, keep moving, and spend at the pace their schedule allows.
    "slow_start": (2, D("0.00")),
    "past_finish": (1, D("0.00")),
    "no_activity": (2, D("0.00")),
    "budget_burn": (2, D("197282.42")),
}


async def find(recon, key: str) -> IssueDetailResponse:
    """Look an issue up by its stable key, whatever its status."""
    issue_id = await recon.db.scalar(select(Issue.id).where(Issue.key == key))
    return await recon.get_issue(issue_id)


async def active_count(recon, **filters) -> int:
    return (await recon.list_issues(IssueFilters(limit=500, **filters))).total


async def act(recon, key: str, **action) -> IssueDetailResponse:
    issue = await find(recon, key)
    return await recon.act_on_issue(issue.id, IssueAction(**action))


async def test_seventeen_issue_types_are_seeded(db):
    assert await db.scalar(select(func.count()).select_from(IssueType)) == 17


async def test_findings_per_type_match_the_export(db):
    rows = (
        await db.execute(
            select(Issue.type_key, func.count(), func.sum(Issue.amount))
            .where(Issue.status.in_(ACTIVE))
            .group_by(Issue.type_key)
        )
    ).all()
    assert {key: (count, amount) for key, count, amount in rows} == EXPECTED
    assert sum(count for _, count, _ in rows) == 65


async def test_issues_go_to_the_ops_manager_then_the_account_executive(recon):
    assert await active_count(recon, owner="Tasha Green") == 11
    # BTX00030002 has no ops manager, so its issues fall to the account executive.
    assert (await find(recon, "past_due:INV-2026-0515")).owner == "Danny Alvarez"
    # A bill with no job has nobody to go to.
    orphan = await find(recon, "no_job:MDC-55201")
    assert (orphan.owner, orphan.job_number) == ("Finance queue", None)


async def test_issue_reads_in_plain_words(recon):
    issue = await find(recon, "past_due:INV-2026-0538")
    assert issue.title == "Customer invoice past due"
    assert issue.amount == D("246300.00")
    assert issue.summary == "INV-2026-0538, 14 days past due"
    assert issue.detail == "INV-2026-0538 to Northgate Independent School District: $246,300 open, 14 days past due."
    assert issue.next_step == "Call the customer's payables contact and log the outcome."
    assert issue.action_label == "Log follow-up"
    assert (await find(recon, "discount:ARS-20447")).summary == "ARS-20447, save $967 by Jul 30"


async def test_each_fact_about_an_issue_is_its_own_field(recon):
    """The document and the date are sent separately, not only inside a sentence."""
    past_due = await find(recon, "past_due:INV-2026-0538")
    assert (past_due.document, past_due.due_on) == ("INV-2026-0538", date(2026, 7, 14))

    discount = await find(recon, "discount:ARS-20447")
    assert (discount.document, discount.due_on) == ("ARS-20447", date(2026, 7, 30))  # last day for the discount

    overdue_bill = await find(recon, "bill_overdue:ARS-20390")
    assert (overdue_bill.document, overdue_bill.due_on) == ("ARS-20390", date(2026, 6, 29))

    unsent = await find(recon, "not_sent:INV-2026-0590")
    assert (unsent.document, unsent.due_on) == ("INV-2026-0590", None)

    # A job-level issue is not about one document and has no deadline.
    job_level = await find(recon, "cost_disagree:CTX00080002")
    assert (job_level.document, job_level.due_on) == (None, None)


async def test_issue_cites_the_money_lines_behind_it(recon):
    issue = await find(recon, "past_due:INV-2026-0538")
    assert [(e.kind, e.doc_number, e.open_amount) for e in issue.evidence] == [
        ("customer_invoice", "INV-2026-0538", D("246300.00"))
    ]
    disagree = await find(recon, "cost_disagree:CTX00080002")
    assert {e.kind for e in disagree.evidence} == {"ops_cost", "ledger_cost"}
    by_kind = lambda kind: sum(e.amount for e in disagree.evidence if e.kind == kind)  # noqa: E731
    assert abs(by_kind("ops_cost") - by_kind("ledger_cost")) == disagree.amount


async def test_resync_changes_nothing(recon, db):
    ids_before = dict((await db.execute(select(Issue.key, Issue.id))).all())
    events_before = await db.scalar(select(func.count()).select_from(IssueEvent))
    stats = (await recon.run_sync()).stats["issues"]
    assert (stats["opened"], stats["reopened"], stats["cleared"], stats["unchanged"]) == (0, 0, 0, 65)
    assert dict((await db.execute(select(Issue.key, Issue.id))).all()) == ids_before
    assert await db.scalar(select(func.count()).select_from(IssueEvent)) == events_before


async def test_resolved_issue_stays_resolved_after_resync(recon):
    key = "no_owner:XAZ00120002"
    await act(recon, key, action="resolve", actor="Rachel Kim", note="Elena Sokolov is covering this job")
    await recon.run_sync()
    issue = await find(recon, key)
    assert (issue.status, issue.resolution_note) == ("resolved", "Elena Sokolov is covering this job")
    assert [e.kind for e in issue.events] == ["opened", "resolved"]
    assert await active_count(recon, type="no_owner") == 6

    reopened = await act(recon, key, action="reopen", actor="Rachel Kim")
    assert (reopened.status, reopened.resolution_note) == ("open", None)
    assert await active_count(recon, type="no_owner") == 7


async def test_assignment_and_comments_survive_a_resync(recon):
    key = "past_due:INV-2026-0515"
    await act(recon, key, action="assign", actor="Rachel Kim", assignee="Jenna Okafor")
    await act(recon, key, action="comment", actor="Jenna Okafor", note="Left a voicemail with their payables desk")
    await recon.run_sync()
    issue = await find(recon, key)
    assert (issue.status, issue.owner) == ("assigned", "Jenna Okafor")
    assert [(e.kind, e.actor) for e in issue.events] == [
        ("opened", "system"), ("assigned", "Rachel Kim"), ("commented", "Jenna Okafor"),
    ]
    assert issue.events[-1].note == "Left a voicemail with their payables desk"


async def test_a_note_keeps_the_issue_open_and_is_counted(recon):
    """Logging a follow-up is not the same as fixing the problem."""
    key = "past_due:INV-2026-0526"
    assert (await find(recon, key)).note_count == 0
    noted = await act(recon, key, action="comment", actor="Tasha Green", note="Called their payables desk")
    assert (noted.status, noted.note_count) == ("open", 1)
    listed = await recon.list_issues(IssueFilters(type="past_due", limit=50))
    assert {i.key: i.note_count for i in listed.data}[key] == 1


async def test_issue_clears_when_the_source_is_fixed_and_reopens_if_it_returns(recon, source):
    key = "not_sent:INV-2026-0590"
    change = text("update source_company.ar_invoices set status = :s where invoice_number = 'INV-2026-0590'")
    await source.execute(change, {"s": "SENT"})
    await source.commit()
    try:
        assert (await recon.run_sync()).stats["issues"]["cleared"] == 1
        cleared = await find(recon, key)
        assert (cleared.status, cleared.events[-1].kind) == ("cleared", "cleared")
        assert await active_count(recon, type="not_sent") == 4
    finally:
        await source.execute(change, {"s": "APPROVED"})
        await source.commit()
    assert (await recon.run_sync()).stats["issues"]["reopened"] == 1
    issue = await find(recon, key)
    assert issue.status == "open"
    assert [e.kind for e in issue.events] == ["opened", "cleared", "reopened"]


async def test_tolerance_is_read_from_the_issue_type(recon):
    await recon.update_issue_type("cost_disagree", IssueTypeUpdate(tolerance=D("0.10")))
    try:
        assert await active_count(recon, type="cost_disagree") == 17  # not until the next sync
        await recon.run_sync()
        assert await active_count(recon, type="cost_disagree") == 9
    finally:
        await recon.update_issue_type("cost_disagree", IssueTypeUpdate(tolerance=D("0.02")))
        await recon.run_sync()
    assert await active_count(recon, type="cost_disagree") == 17


async def test_disabling_an_issue_type_clears_its_issues(recon):
    await recon.update_issue_type("discount", IssueTypeUpdate(enabled=False))
    try:
        await recon.run_sync()
        assert await active_count(recon, type="discount") == 0
    finally:
        await recon.update_issue_type("discount", IssueTypeUpdate(enabled=True))
        await recon.run_sync()
    assert await active_count(recon, type="discount") == 3


async def test_actions_are_validated(recon):
    key = "no_job:DTL-9954"
    with pytest.raises(InvalidRequestError, match="needs a note"):
        await act(recon, key, action="resolve", actor="Rachel Kim")
    with pytest.raises(InvalidRequestError, match="assignee"):
        await act(recon, key, action="assign", actor="Rachel Kim")
    with pytest.raises(InvalidStateError, match="Only a resolved or cleared"):
        await act(recon, key, action="reopen", actor="Rachel Kim")
    with pytest.raises(InvalidRequestError, match="no tolerance"):
        await recon.update_issue_type("no_owner", IssueTypeUpdate(tolerance=D("0.5")))
    issue = await find(recon, key)
    assert (issue.status, [e.kind for e in issue.events]) == ("open", ["opened"])


def test_checks_toml_and_the_check_functions_match():
    """Every block in checks.toml has a @check function and every @check function has a
    block, and each block is complete and uses known values. If this fails, the file and
    the code have drifted apart."""
    from app.checks.issues import CHECKS, DEFINITIONS

    assert set(DEFINITIONS) == set(CHECKS)
    for d in DEFINITIONS.values():
        assert d.title and d.description, d.key
        assert d.severity in ("high", "medium"), d.key
        assert d.about in ("cash", "billing", "cost", "schedule", "ownership"), d.key
        assert (d.tolerance is None) == (d.unit is None), f"{d.key}: tolerance and unit go together"
        assert d.unit in (None, "ratio", "usd", "days"), d.key
