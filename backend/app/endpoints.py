"""HTTP endpoint definitions."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from app.client import create_recon_client
from app.financials import CostBasis, RevenueBasis
from app.middleware import require_api_key
from app.schemas import (
    AskRequest,
    AskResponse,
    CustomerBalance,
    ErrorResponse,
    IssueAction,
    IssueDetailResponse,
    IssueFilters,
    IssueResponse,
    CodingResponse,
    DraftRequest,
    DraftResponse,
    IssueTypeResponse,
    SourceSystem,
    PersonResponse,
    IssueTypeUpdate,
    JobDetailResponse,
    JobFilters,
    JobSummaryResponse,
    LineFilters,
    LineResponse,
    ListResponse,
    Paging,
    SourceRecordResponse,
    SummaryResponse,
    SyncRunCreate,
    SyncRunResponse,
)

ERROR_400 = {"model": ErrorResponse, "description": "The request is missing something this action needs."}
ERROR_401 = {"model": ErrorResponse, "description": "Missing or wrong API key."}
ERROR_404 = {"model": ErrorResponse, "description": "Resource not found."}
ERROR_409 = {"model": ErrorResponse, "description": "The current state does not allow this."}
ERROR_500 = {"model": ErrorResponse, "description": "Unexpected server error."}
ERROR_502 = {"model": ErrorResponse, "description": "The model could not answer."}
ERROR_503 = {"model": ErrorResponse, "description": "Ask has no API key configured."}

health_router = APIRouter()
router = APIRouter(
    prefix="/api/v1",
    dependencies=[Depends(require_api_key)],
    responses={401: ERROR_401, 500: ERROR_500},
)


@health_router.get("/health", tags=["Health"], summary="Liveness check")
async def health(request: Request) -> dict[str, str]:
    async with create_recon_client(request.state.request_id) as client:
        return await client.ping()


@router.post(
    "/sync-runs",
    tags=["Sync Runs"],
    summary="Run a sync",
    status_code=status.HTTP_201_CREATED,
    response_model=SyncRunResponse,
)
async def run_sync(request: Request, payload: SyncRunCreate | None = None) -> SyncRunResponse:
    async with create_recon_client(request.state.request_id) as client:
        return await client.run_sync(payload.as_of if payload else None)


@router.get("/sync-runs", tags=["Sync Runs"], response_model=ListResponse[SyncRunResponse])
async def list_sync_runs(paging: Annotated[Paging, Query()], request: Request) -> ListResponse[SyncRunResponse]:
    async with create_recon_client(request.state.request_id) as client:
        return await client.list_sync_runs(paging)


@router.get(
    "/sync-runs/{run_id}",
    tags=["Sync Runs"],
    response_model=SyncRunResponse,
    responses={404: ERROR_404},
)
async def get_sync_run(run_id: int, request: Request) -> SyncRunResponse:
    async with create_recon_client(request.state.request_id) as client:
        return await client.get_sync_run(run_id)


@router.get(
    "/summary",
    tags=["Summary"],
    summary="Cash position and issues at a glance",
    response_model=SummaryResponse,
    responses={409: ERROR_409},
)
async def get_summary(
    request: Request,
    owner: Annotated[str | None, Query(description="Limit to one ops manager's jobs and issues")] = None,
) -> SummaryResponse:
    async with create_recon_client(request.state.request_id) as client:
        return await client.get_summary(owner)


@router.get(
    "/jobs",
    tags=["Jobs"],
    response_model=ListResponse[JobSummaryResponse],
    responses={409: ERROR_409},
)
async def list_jobs(filters: Annotated[JobFilters, Query()], request: Request) -> ListResponse[JobSummaryResponse]:
    async with create_recon_client(request.state.request_id) as client:
        return await client.list_jobs(filters)


@router.get(
    "/jobs/{job_number}",
    tags=["Jobs"],
    summary="One job, with revenue and cost figures side by side",
    response_model=JobDetailResponse,
    responses={404: ERROR_404, 409: ERROR_409},
)
async def get_job(
    job_number: str,
    request: Request,
    revenue: Annotated[RevenueBasis, Query(description="Which revenue figure to use for profit")] = RevenueBasis.ledger,
    cost: Annotated[CostBasis, Query(description="Which cost figure to use for profit")] = CostBasis.ledger,
) -> JobDetailResponse:
    async with create_recon_client(request.state.request_id) as client:
        return await client.get_job(job_number, revenue, cost)


@router.get(
    "/jobs/{job_number}/lines",
    tags=["Jobs"],
    response_model=list[LineResponse],
    responses={404: ERROR_404, 409: ERROR_409},
)
async def list_job_lines(
    job_number: str,
    request: Request,
    kind: Annotated[str | None, Query(description="ops_cost, ledger_cost, ledger_revenue, vendor_bill, ...")] = None,
) -> list[LineResponse]:
    async with create_recon_client(request.state.request_id) as client:
        return await client.list_job_lines(job_number, kind)


@router.get(
    "/lines",
    tags=["Invoices and Bills"],
    summary="Invoices or vendor bills across jobs",
    response_model=ListResponse[LineResponse],
    responses={409: ERROR_409},
)
async def list_lines(filters: Annotated[LineFilters, Query()], request: Request) -> ListResponse[LineResponse]:
    async with create_recon_client(request.state.request_id) as client:
        return await client.list_lines(filters)


@router.get(
    "/customer-balances",
    tags=["Invoices and Bills"],
    summary="What each customer owes, largest first",
    response_model=list[CustomerBalance],
    responses={409: ERROR_409},
)
async def list_customer_balances(
    request: Request,
    owner: Annotated[str | None, Query(description="Limit to one ops manager's jobs")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
) -> list[CustomerBalance]:
    async with create_recon_client(request.state.request_id) as client:
        return await client.list_customer_balances(owner, limit)


@router.post(
    "/ask",
    tags=["Ask"],
    summary="Ask a question about the data in plain words",
    response_model=AskResponse,
    responses={409: ERROR_409, 502: ERROR_502, 503: ERROR_503},
)
async def ask(payload: AskRequest, request: Request) -> AskResponse:
    async with create_recon_client(request.state.request_id) as client:
        return await client.ask(payload)


@router.get(
    "/ask/history",
    tags=["Ask"],
    summary="One person's saved conversation, oldest first",
    response_model=list[AskResponse],
)
async def list_ask_history(
    request: Request,
    asked_by: Annotated[str, Query(min_length=1, max_length=120, description="Whose conversation")],
) -> list[AskResponse]:
    async with create_recon_client(request.state.request_id) as client:
        return await client.list_ask_history(asked_by)


@router.delete(
    "/ask/history",
    tags=["Ask"],
    summary="Clear one person's saved conversation",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def clear_ask_history(
    request: Request,
    asked_by: Annotated[str, Query(min_length=1, max_length=120, description="Whose conversation")],
) -> None:
    async with create_recon_client(request.state.request_id) as client:
        await client.clear_ask_history(asked_by)


@router.get("/issues", tags=["Issues"], response_model=ListResponse[IssueResponse])
async def list_issues(filters: Annotated[IssueFilters, Query()], request: Request) -> ListResponse[IssueResponse]:
    async with create_recon_client(request.state.request_id) as client:
        return await client.list_issues(filters)


@router.get(
    "/issues/{issue_id}",
    tags=["Issues"],
    response_model=IssueDetailResponse,
    responses={404: ERROR_404},
)
async def get_issue(issue_id: int, request: Request) -> IssueDetailResponse:
    async with create_recon_client(request.state.request_id) as client:
        return await client.get_issue(issue_id)


@router.post(
    "/issues/{issue_id}/actions",
    tags=["Issues"],
    summary="Update, resolve or reopen an issue",
    response_model=IssueDetailResponse,
    responses={400: ERROR_400, 404: ERROR_404, 409: ERROR_409},
)
async def act_on_issue(issue_id: int, payload: IssueAction, request: Request) -> IssueDetailResponse:
    async with create_recon_client(request.state.request_id) as client:
        return await client.act_on_issue(issue_id, payload)


@router.post(
    "/issues/{issue_id}/draft",
    tags=["Issues"],
    summary="Draft a follow-up message about an issue. Nothing is sent",
    response_model=DraftResponse,
    responses={404: ERROR_404, 409: ERROR_409},
)
async def draft_follow_up(issue_id: int, payload: DraftRequest, request: Request) -> DraftResponse:
    async with create_recon_client(request.state.request_id) as client:
        return await client.draft_follow_up(issue_id, payload)


@router.post(
    "/issues/{issue_id}/coding",
    tags=["Issues"],
    summary="Suggest which job an unassigned vendor bill belongs to. Nothing is changed",
    response_model=CodingResponse,
    responses={400: ERROR_400, 404: ERROR_404, 409: ERROR_409},
)
async def suggest_job_for_issue(issue_id: int, request: Request) -> CodingResponse:
    async with create_recon_client(request.state.request_id) as client:
        return await client.suggest_job_for_issue(issue_id)


@router.get("/sources", tags=["Sync Runs"], summary="The source systems and when each was last read", response_model=list[SourceSystem])
async def list_sources(request: Request) -> list[SourceSystem]:
    async with create_recon_client(request.state.request_id) as client:
        return await client.list_sources()


@router.get("/people", tags=["Issues"], summary="Who an issue can be assigned to", response_model=list[PersonResponse])
async def list_people(request: Request) -> list[PersonResponse]:
    async with create_recon_client(request.state.request_id) as client:
        return await client.list_people()


@router.get("/issue-types", tags=["Issue Types"], response_model=list[IssueTypeResponse])
async def list_issue_types(request: Request) -> list[IssueTypeResponse]:
    async with create_recon_client(request.state.request_id) as client:
        return await client.list_issue_types()


@router.patch(
    "/issue-types/{key}",
    tags=["Issue Types"],
    summary="Switch a check off or change its tolerance",
    response_model=IssueTypeResponse,
    responses={400: ERROR_400, 404: ERROR_404},
)
async def update_issue_type(key: str, payload: IssueTypeUpdate, request: Request) -> IssueTypeResponse:
    async with create_recon_client(request.state.request_id) as client:
        return await client.update_issue_type(key, payload)


@router.get(
    "/source-records/{record_id}",
    tags=["Source Records"],
    summary="The untouched source row behind any number",
    response_model=SourceRecordResponse,
    responses={404: ERROR_404},
)
async def get_source_record(record_id: int, request: Request) -> SourceRecordResponse:
    async with create_recon_client(request.state.request_id) as client:
        return await client.get_source_record(record_id)
