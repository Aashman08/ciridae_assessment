"""Request-ID middleware and the optional API key check."""

import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Header, Request, Response

from app.database import settings
from app.errors import UnauthorizedError

REQUEST_ID_HEADER = "X-Request-ID"


async def request_id_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers[REQUEST_ID_HEADER] = request_id
    return response


async def require_api_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    """Open by default. When API_KEY is set, every request must send it."""
    if settings.api_key and x_api_key != settings.api_key:
        raise UnauthorizedError()
