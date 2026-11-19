"""FastAPI application declaration and registration."""

from fastapi import FastAPI

from app.database import lifespan
from app.endpoints import health_router, router
from app.errors import APIError
from app.exception_handlers import api_error_response
from app.middleware import request_id_middleware

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
