"""Runs one sync from start to finish and records what it did."""

from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_source_engine
from app.models import SyncRun
from app.sync.connector import Connector, ExportConnector
from app.sync.financials import compute_financials
from app.sync.issues import find_issues
from app.sync.land import land
from app.sync.normalize import normalize


def default_as_of(connector: Connector) -> date:
    """The export's own date. Measuring 'past due' against today would make
    every invoice in a months-old export look late."""
    value = connector.metadata("dataset_as_of")
    return date.fromisoformat(value) if value else date.today()


def run_sync(session: Session, as_of: date | None = None, connector: Connector | None = None) -> SyncRun:
    connector = connector or ExportConnector(get_source_engine(), get_settings().source_schema)
    run = SyncRun(as_of=as_of or default_as_of(connector), status="running", stats={})
    session.add(run)
    session.commit()

    try:
        stats = {"land": land(session, run, connector)}
        stats["normalize"] = normalize(session, run)
        stats["financials"] = compute_financials(session, run)
        stats["issues"] = find_issues(session, run)
        run.stats = stats
        run.status = "succeeded"
    except Exception as exc:
        session.rollback()
        run = session.get(SyncRun, run.id)
        run.status = "failed"
        run.error = f"{type(exc).__name__}: {exc}"
        run.finished_at = datetime.now(timezone.utc)
        session.commit()
        raise
    run.finished_at = datetime.now(timezone.utc)
    session.commit()
    return run
