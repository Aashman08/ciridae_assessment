"""FastAPI application declaration and registration."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core import database
from app.sync.scheduler import sync_on_schedule
from app.endpoints import health_router, router
from app.core.errors import APIError
from app.core.exception_handlers import api_error_response
from app.core.middleware import request_id_middleware

# Our own messages (sync results, what each Ask question used) go to the terminal.
logging.getLogger("app").setLevel(logging.INFO)
logging.basicConfig(format="%(levelname)s:     %(name)s: %(message)s")

@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Migrate, then keep the figures current on a schedule until shutdown."""
    async with database.lifespan(application):
        every = database.settings.sync_every_minutes
        schedule = asyncio.create_task(sync_on_schedule(every)) if every > 0 else None
        try:
            yield
        finally:
            if schedule:
                schedule.cancel()


app = FastAPI(
    title="Harborstone Reconciliation API",
    version="0.1.0",
    description=(
        "Reads Harborstone's CRM, project and accounting records, joins them into one "
        "record per job, and reports where the three systems disagree. Every figure "
        "traces back to a source record. Amounts are decimal strings "
        '(e.g. "246300.00"); dates are ISO 8601. Start with `POST /api/v1/sync-runs`.'
    ),
    lifespan=lifespan,
    exception_handlers={
        APIError: api_error_response,
        Exception: api_error_response,
    },
)

app.middleware("http")(request_id_middleware)
app.include_router(health_router)
app.include_router(router)
