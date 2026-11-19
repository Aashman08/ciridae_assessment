from decimal import Decimal

import pytest
from sqlalchemy import func, select, text, update

from app.models import Issue, IssueEvent, IssueType, MoneyLine
from app.sync.issues import IssueActionError, apply_action
from app.sync.runner import run_sync

D = Decimal
ACTIVE = ("open", "assigned")

# What the export holds as of 28 July 2026: findings and dollars per issue type.
EXPECTED = {
    "past_due": (5, D("719004.00")),
    "not_sent": (5, D("369100.00")),
    "cost_disagree": (17, D("227005.00")),
    "no_ledger_cost": (2, D("197140.00")),
    "closed_bills": (6, D("187190.00")),
    "closed_month": (5, D("172810.00")),
    "bill_overdue": (5, D("172810.00")),
    "rev_invoiced": (2, D("127600.00")),
    "discount": (3, D("72370.00")),
    "underbilled": (1, D("19900.00")),
    "over_contract": (1, D("14040.00")),
    "no_job": (3, D("8985.00")),
    "no_owner": (7, D("0.00")),
}


@pytest.fixture(scope="module", autouse=True)
def synced(database):
    from app.db import new_session

    with new_session() as s:
        run_sync(s)


def active(session, *where):
    return session.scalars(select(Issue).where(Issue.status.in_(ACTIVE), *where)).all()


def get(session, key) -> Issue:
    session.expire_all()
    return session.scalar(select(Issue).where(Issue.key == key))


def test_thirteen_issue_types_are_seeded(session):
    assert session.scalar(select(func.count()).select_from(IssueType)) == 13


def test_findings_per_type_match_the_export(session):
    rows = session.execute(
        select(Issue.type_key, func.count(), func.sum(Issue.amount)).where(Issue.status.in_(ACTIVE)).group_by(Issue.type_key)
    ).all()
    assert {key: (count, amount) for key, count, amount in rows} == EXPECTED
    assert sum(count for _, count, _ in rows) == 62


def test_issues_go_to_the_ops_manager_then_the_account_executive(session):
    assert len(active(session, Issue.owner == "Tasha Green")) == 10
    # BTX00030002 has no ops manager, so its issues fall to the account executive.
    assert get(session, "past_due:INV-2026-0515").owner == "Danny Alvarez"
    # A bill with no job has nobody to go to.
    assert get(session, "no_job:MDC-55201").owner == "Finance queue"
    assert get(session, "no_job:MDC-55201").job_id is None


def test_issue_reads_in_plain_words(session):
    issue = get(session, "past_due:INV-2026-0538")
    assert issue.amount == D("246300.00")
    assert issue.summary == "INV-2026-0538, 14 days past due"
    assert issue.detail == "INV-2026-0538 to Northgate Independent School District: $246,300 open, 14 days past due."
    assert issue.action_label == "Log follow-up"

    discount = get(session, "discount:ARS-20447")
    assert discount.summary == "ARS-20447, save $967 by Jul 30"


def test_issue_cites_the_money_lines_behind_it(session):
    issue = get(session, "past_due:INV-2026-0538")
    cited = [e.line for e in issue.evidence]
    assert [(l.kind, l.doc_number) for l in cited] == [("customer_invoice", "INV-2026-0538")]

    disagree = get(session, "cost_disagree:CTX00080002")
    kinds = {e.line.kind for e in disagree.evidence}
    assert kinds == {"ops_cost", "ledger_cost"}
    by_kind = lambda k: sum(e.line.amount for e in disagree.evidence if e.line.kind == k)  # noqa: E731
    assert abs(by_kind("ops_cost") - by_kind("ledger_cost")) == disagree.amount


def test_resync_changes_nothing(session):
    ids_before = dict(session.execute(select(Issue.key, Issue.id)).all())
    events_before = session.scalar(select(func.count()).select_from(IssueEvent))
    stats = run_sync(session).stats["issues"]
    assert (stats["opened"], stats["reopened"], stats["cleared"]) == (0, 0, 0)
    assert stats["unchanged"] == 62
    assert dict(session.execute(select(Issue.key, Issue.id)).all()) == ids_before
    assert session.scalar(select(func.count()).select_from(IssueEvent)) == events_before


def test_resolved_issue_stays_resolved_after_resync(session):
    issue = get(session, "no_owner:XAZ00120002")
    apply_action(session, issue, "resolve", actor="Rachel Kim", note="Elena Sokolov is covering this job")
    session.commit()
    run_sync(session)
    issue = get(session, "no_owner:XAZ00120002")
    assert issue.status == "resolved"
    assert issue.resolution_note == "Elena Sokolov is covering this job"
    assert [e.kind for e in issue.events] == ["opened", "resolved"]
    apply_action(session, issue, "reopen", actor="Rachel Kim")
    session.commit()


def test_assignment_and_comments_survive_a_resync(session):
    issue = get(session, "past_due:INV-2026-0515")
    apply_action(session, issue, "assign", actor="Rachel Kim", assignee="Jenna Okafor")
    apply_action(session, issue, "comment", actor="Jenna Okafor", note="Left a voicemail with their payables desk")
    session.commit()
    run_sync(session)
    issue = get(session, "past_due:INV-2026-0515")
    assert (issue.status, issue.owner) == ("assigned", "Jenna Okafor")
    # Earlier syncs with other as-of dates may have cleared and reopened this
    # issue, so only the tail of its history is fixed.
    assert [e.kind for e in issue.events][-2:] == ["assigned", "commented"]
    assert issue.events[-1].note == "Left a voicemail with their payables desk"


def test_issue_clears_when_the_source_is_fixed_and_reopens_if_it_returns(session, source):
    fix = "update source_company.ar_invoices set status = :s where invoice_number = 'INV-2026-0590'"
    source.execute(text(fix), {"s": "SENT"})
    source.commit()
    try:
        stats = run_sync(session).stats["issues"]
        assert stats["cleared"] == 1
        issue = get(session, "not_sent:INV-2026-0590")
        assert issue.status == "cleared"
        assert issue.events[-1].kind == "cleared"
    finally:
        source.execute(text(fix), {"s": "APPROVED"})
        source.commit()
    stats = run_sync(session).stats["issues"]
    assert stats["reopened"] == 1
    issue = get(session, "not_sent:INV-2026-0590")
    assert issue.status == "open"
    assert [e.kind for e in issue.events] == ["opened", "cleared", "reopened"]


def test_tolerance_is_read_from_the_issue_type(session):
    session.execute(update(IssueType).where(IssueType.key == "cost_disagree").values(tolerance=D("0.10")))
    session.commit()
    try:
        run_sync(session)
        assert len(active(session, Issue.type_key == "cost_disagree")) == 9
    finally:
        session.execute(update(IssueType).where(IssueType.key == "cost_disagree").values(tolerance=D("0.02")))
        session.commit()
        run_sync(session)
    assert len(active(session, Issue.type_key == "cost_disagree")) == 17


def test_disabling_an_issue_type_clears_its_issues(session):
    session.execute(update(IssueType).where(IssueType.key == "discount").values(enabled=False))
    session.commit()
    try:
        run_sync(session)
        assert active(session, Issue.type_key == "discount") == []
    finally:
        session.execute(update(IssueType).where(IssueType.key == "discount").values(enabled=True))
        session.commit()
        run_sync(session)
    assert len(active(session, Issue.type_key == "discount")) == 3


def test_actions_are_validated(session):
    issue = get(session, "no_job:DTL-9954")
    with pytest.raises(IssueActionError, match="needs a note"):
        apply_action(session, issue, "resolve", actor="Rachel Kim")
    with pytest.raises(IssueActionError, match="assignee"):
        apply_action(session, issue, "assign", actor="Rachel Kim")
    with pytest.raises(IssueActionError, match="Only a resolved or cleared"):
        apply_action(session, issue, "reopen", actor="Rachel Kim")
    session.rollback()


def test_money_lines_are_untouched_by_issue_runs(session):
    assert session.scalar(select(func.count()).select_from(MoneyLine)) == 194
