"""Syncing on a schedule, so nobody has to press a button to get current figures."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app import database
from app.client import create_recon_client
from app.models import SyncRun

logger = logging.getLogger(__name__)


async def _wait_before_first_run(every: timedelta) -> float:
    """Seconds until the next sync is due. None has ever run: now. Otherwise the
    interval is counted from the last one, so restarting the service does not re-sync."""
    async with database.SessionLocal() as db:
        last = await db.scalar(
            select(SyncRun.finished_at).where(SyncRun.status == "succeeded").order_by(SyncRun.id.desc()).limit(1)
        )
    if last is None:
        return 0
    return max(0.0, (last + every - datetime.now(UTC)).total_seconds())


async def sync_on_schedule(every_minutes: int) -> None:
    """Run a sync every `every_minutes`, for as long as the service is up. A failed
    run is recorded by the sync itself and tried again at the next interval."""
    every = timedelta(minutes=every_minutes)
    await asyncio.sleep(await _wait_before_first_run(every))
    while True:
        try:
            async with create_recon_client("scheduled-sync") as client:
                run = await client.run_sync()
            logger.info("Scheduled sync %s finished as_of=%s", run.id, run.as_of)
        except Exception:
            logger.exception("Scheduled sync failed; trying again in %s minutes", every_minutes)
        await asyncio.sleep(every.total_seconds())
