"""HTTP endpoint definitions."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from app.client import create_recon_client
from app.financials import CostBasis, RevenueBasis
from app.middleware import require_api_key
from app.schemas import (
    ErrorResponse,
    IssueAction,
    IssueDetailResponse,
    IssueFilters,
    IssueResponse,
    IssueTypeResponse,
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
    summary="Assign, comment on, resolve or reopen an issue",
    response_model=IssueDetailResponse,
    responses={400: ERROR_400, 404: ERROR_404, 409: ERROR_409},
)
async def act_on_issue(issue_id: int, payload: IssueAction, request: Request) -> IssueDetailResponse:
    async with create_recon_client(request.state.request_id) as client:
        return await client.act_on_issue(issue_id, payload)


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
