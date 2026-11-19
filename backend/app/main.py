from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.routes import router
from app.db import get_session

app = FastAPI(
    title="Closeout",
    version="0.1.0",
    summary="Reconciles each Harborstone job across CRM, project management and accounting.",
    description=(
        "Pulls records from the three source systems, joins them into one record per job, "
        "and reports where the systems disagree. Every figure traces back to a source record. "
        "Start with `POST /api/v1/sync-runs`, then read `/api/v1/summary`, `/api/v1/jobs` and `/api/v1/issues`."
    ),
)


@app.get("/health", tags=["service"])
def health(session: Session = Depends(get_session)) -> dict:
    """Confirms the service is up and can reach its database."""
    session.execute(text("select 1"))
    return {"status": "ok"}


app.include_router(router)
