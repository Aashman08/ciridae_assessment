"""Sync step 1: copy every source row into `raw.source_record`, untouched.

A row is rewritten only when its content hash changes, so a sync with no
source changes rewrites nothing. Rows that disappear from the source are
kept, and can be told apart because their `last_seen_run_id` stops advancing.
"""

import hashlib
import json

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.sync.connector import SYSTEM_BY_TABLE, Connector
from app.core.models import SourceRecord, SyncRun


def content_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


async def land(db: AsyncSession, run: SyncRun, connector: Connector) -> dict:
    known_rows = await db.execute(
        select(SourceRecord.id, SourceRecord.table_name, SourceRecord.source_pk, SourceRecord.content_hash)
    )
    existing = {(table, pk): (record_id, digest) for record_id, table, pk, digest in known_rows}

    stats = {"tables": 0, "rows": 0, "new": 0, "changed": 0, "unchanged": 0}
    seen_ids: list[int] = []

    for table in await connector.tables():
        stats["tables"] += 1
        for pk, payload in await connector.rows(table):
            stats["rows"] += 1
            digest = content_hash(payload)
            known = existing.get((table, pk))
            if known is None:
                db.add(
                    SourceRecord(
                        system=SYSTEM_BY_TABLE.get(table, "unknown"),
                        table_name=table,
                        source_pk=pk,
                        payload=payload,
                        content_hash=digest,
                        first_seen_run_id=run.id,
                        last_changed_run_id=run.id,
                        last_seen_run_id=run.id,
                    )
                )
                stats["new"] += 1
            elif known[1] != digest:
                await db.execute(
                    update(SourceRecord)
                    .where(SourceRecord.id == known[0])
                    .values(payload=payload, content_hash=digest, last_changed_run_id=run.id, last_seen_run_id=run.id)
                )
                stats["changed"] += 1
            else:
                seen_ids.append(known[0])
                stats["unchanged"] += 1

    if seen_ids:
        await db.execute(update(SourceRecord).where(SourceRecord.id.in_(seen_ids)).values(last_seen_run_id=run.id))
    await db.flush()
    stats["missing_from_source"] = len(existing) - stats["changed"] - stats["unchanged"]
    return stats
