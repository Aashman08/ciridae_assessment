from fastapi import Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.models import SyncRun
from app.sync.financials import latest_run_id


def require_api_key(x_api_key: str | None = Header(None)) -> None:
    """Open by default. If API_KEY is set, every request must send it."""
    expected = get_settings().api_key
    if expected and x_api_key != expected:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Send the API key in the X-API-Key header")


def current_run(session: Session = Depends(get_session)) -> SyncRun:
    """The latest finished sync. Everything the API reads comes from it."""
    run_id = latest_run_id(session)
    if run_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "No sync has finished yet. POST /api/v1/sync-runs to run one")
    return session.get(SyncRun, run_id)


class Paging:
    def __init__(
        self,
        limit: int = Query(50, ge=1, le=500, description="How many to return"),
        offset: int = Query(0, ge=0, description="How many to skip"),
    ):
        self.limit = limit
        self.offset = offset

    def page(self, items: list) -> dict:
        return {
            "items": items[self.offset : self.offset + self.limit],
            "total": len(items),
            "limit": self.limit,
            "offset": self.offset,
        }
