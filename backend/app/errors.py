"""Application exceptions. HTTP response handling lives in exception_handlers.py."""


class APIError(Exception):
    status_code = 500
    error_type = "internal_error"
    message = "An unexpected error occurred. Quote the request ID when contacting support."

    def __init__(self, message: str | None = None) -> None:
        self.message = message if message is not None else self.message
        super().__init__(self.message)


class UnauthorizedError(APIError):
    status_code = 401
    error_type = "unauthorized"
    message = "Send the API key in the X-API-Key header."


class InvalidRequestError(APIError):
    status_code = 400
    error_type = "invalid_request"
    message = "The request is missing something this action needs."


class NotFoundError(APIError):
    status_code = 404
    error_type = "not_found"
    message = "The requested resource was not found."


class InvalidStateError(APIError):
    status_code = 409
    error_type = "invalid_state"
    message = "The resource's current state does not allow this action."


class JobNotFoundError(NotFoundError):
    def __init__(self, job_number: str) -> None:
        super().__init__(f"No job found with number '{job_number}'.")


class IssueNotFoundError(NotFoundError):
    def __init__(self, issue_id: int) -> None:
        super().__init__(f"No issue found with id {issue_id}.")


class IssueTypeNotFoundError(NotFoundError):
    def __init__(self, key: str) -> None:
        super().__init__(f"No issue type found with key '{key}'.")


class SyncRunNotFoundError(NotFoundError):
    def __init__(self, run_id: int) -> None:
        super().__init__(f"No sync run found with id {run_id}.")


class SourceRecordNotFoundError(NotFoundError):
    def __init__(self, record_id: int) -> None:
        super().__init__(f"No source record found with id {record_id}.")


class NoSyncYetError(InvalidStateError):
    message = "No sync has finished yet. POST /api/v1/sync-runs to run one."
