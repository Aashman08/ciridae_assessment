import type { Spec } from '@json-render/core'
// Everything the app knows about the backend lives here: the shapes it returns
// and the one function that calls it.

/** Dollars and cents as a string, e.g. "246300.00". The API never sends money as a number. */
export type Money = string

export interface ListResponse<T> {
  data: T[]
  total: number
  has_more: boolean
}

export interface SyncRun {
  id: number
  status: string
  as_of: string
  started_at: string
  finished_at: string | null
  error: string | null
}

export interface Line {
  id: number
  kind: string
  doc_number: string | null
  description: string | null
  job_number: string | null
  company: string | null
  amount: Money
  paid_amount: Money
  open_amount: Money
  line_date: string | null
  due_date: string | null
  status: string | null
  source_table: string
  source_record_id: number
}

export interface Issue {
  id: number
  key: string
  type_key: string
  title: string
  severity: 'high' | 'medium'
  about: string
  job_number: string | null
  job_name: string | null
  subject: string
  /** The invoice or bill this is about. Null for job-level issues. */
  document: string | null
  /** The date something has to happen by, when there is one. */
  due_on: string | null
  amount: Money
  summary: string
  detail: string
  next_step: string
  action_label: string
  owner: string
  /** Why the owner has it. `account_executive` means the job has no ops manager. */
  owner_role: 'ops_manager' | 'account_executive' | 'finance' | 'assigned'
  status: 'open' | 'assigned' | 'resolved' | 'cleared'
  resolution_note: string | null
  /** How many notes people have left on this issue. */
  note_count: number
  /** A date someone set to come back to this. */
  follow_up_on: string | null
  /** Days past `due_on` as of the sync date. Null when not yet due. */
  days_late: number | null
  /** Other open issues about the same invoice or bill. It is the same money. */
  same_document: number
  first_seen_on: string
  updated_at: string
}

export interface IssueEvent {
  id: number
  kind: string
  actor: string
  note: string | null
  created_at: string
}

export interface IssueDetail extends Issue {
  evidence: Line[]
  events: IssueEvent[]
  /** Other open issues about the same invoice or bill. */
  related: { id: number; title: string; severity: 'high' | 'medium'; amount: Money }[]
}

/** Someone an issue can belong to. */
export interface Person {
  name: string
  roles: string[]
}

/** What "Log update" saves: any of a note, a new owner and a follow-up date. */
export interface IssueUpdate {
  action: 'update' | 'resolve' | 'reopen'
  actor: string
  note?: string
  assignee?: string
  follow_up_on?: string
  clear_follow_up?: boolean
}

export type Order = 'asc' | 'desc'
export type JobSort =
  | 'issues'
  | 'job_number'
  | 'name'
  | 'contract'
  | 'revenue'
  | 'cost'
  | 'profit'
  | 'margin'
  | 'planned_margin'
  | 'owed'
export type IssueSort = 'amount' | 'severity' | 'due' | 'follow_up' | 'owner'

export interface IssueType {
  key: string
  title: string
  severity: 'high' | 'medium'
  about: string
  description: string
  enabled: boolean
  tolerance: string | null
  tolerance_unit: 'ratio' | 'usd' | null
  open_count: number
  open_amount: Money
}

export interface JobSummary {
  job_number: string
  name: string
  customer: string | null
  stage: string
  branch: string | null
  service_line: string | null
  ops_manager: string | null
  account_executive: string | null
  contract_value: Money
  budget: Money
  planned_margin_pct: string | null
  /** Ledger revenue less ledger cost. */
  ledger_profit: Money
  /** Ledger profit as a share of ledger revenue. Null with no revenue. */
  ledger_margin_pct: string | null
  ledger_revenue: Money
  invoiced: Money
  sent: Money
  collected: Money
  owed: Money
  past_due: Money
  ops_cost: Money
  ledger_cost: Money
  unpaid_bills: Money
  issue_count: number
  top_issue: { type_key: string; title: string; amount: Money } | null
}

export type RevenueBasis = 'ledger' | 'invoiced' | 'collected'
export type CostBasis = 'ops_log' | 'ledger' | 'ledger_plus_unpaid_bills'

export interface FigureOption<Basis extends string> {
  basis: Basis
  label: string
  description: string
  amount: Money
}

export interface JobDetail extends JobSummary {
  estimated_value: Money | null
  original_contract_value: Money | null
  won_on: string | null
  on_site_on: string | null
  planned_finish_on: string | null
  completed_on: string | null
  closed_on: string | null
  cancelled_on: string | null
  revenue_options: FigureOption<RevenueBasis>[]
  cost_options: FigureOption<CostBasis>[]
  profit: {
    revenue: Money
    cost: Money
    profit: Money
    margin_pct: string | null
    planned_margin_pct: string | null
  }
  issues: Issue[]
  invoices: Line[]
  vendor_bills: Line[]
}

export interface Summary {
  sync_run_id: number
  as_of: string
  owner: string | null
  job_count: number
  cash: {
    owed: Money
    past_due: Money
    invoices_not_sent: Money
    invoices_not_sent_count: number
    vendor_bills_unpaid: Money
    vendor_bills_count: number
    invoice_count: number
  }
  contract_to_cash: {
    contract_value: Money
    earned: Money
    invoiced: Money
    sent: Money
    collected: Money
  }
  open_issue_count: number
  jobs_with_issues: number
  issues_by_type: { type_key: string; title: string; severity: string; count: number; amount: Money }[]
  /** Invoices and bills with an open issue, each counted once, and what is unpaid on them. */
  flagged_documents: { count: number; amount: Money }
}

export interface AskSource {
  kind: 'job' | 'issue' | 'invoice' | 'vendor_bill'
  /** Job number for a job, invoice or bill; issue id for an issue. */
  id: string
  label: string
}

/** One fixed lookup the assistant ran, with the inputs it chose. */
export interface AskStep {
  tool: string
  arguments: Record<string, unknown>
}

/** One saved exchange: a question, its answer, and what the answer rests on. */
export interface AskResponse {
  id: number
  question: string
  asked_by: string
  created_at: string
  /** The whole answer as plain text. */
  answer: string
  /** The answer laid out for display: text, tables and figures, drawn by `AnswerView`. */
  spec: Spec
  sources: AskSource[]
  steps: AskStep[]
  /** Dollar figures in the answer that no lookup returned: the assistant calculated them. */
  worked_out: string[]
  as_of: string
}

export interface SourceRecord {
  id: number
  system: string
  table_name: string
  source_pk: string
  payload: Record<string, unknown>
}

/** An error the API explained. `requestId` is what to quote when asking for help. */
export class ApiError extends Error {
  status: number
  type: string
  requestId: string

  constructor(status: number, type: string, message: string, requestId: string) {
    super(message)
    this.status = status
    this.type = type
    this.requestId = requestId
  }
}

type Params = Record<string, string | number | boolean | null | undefined>

function query(params: Params = {}): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api/v1${path}`, {
      ...init,
      headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
    })
  } catch {
    throw new ApiError(0, 'unreachable', 'The reconciliation service is not responding. Check that it is running.', '')
  }
  // A delete answers with no body.
  if (response.status === 204) return undefined as T
  if (response.ok) return response.json() as Promise<T>

  const requestId = response.headers.get('X-Request-ID') ?? ''
  const body = await response.json().catch(() => null)
  if (body?.error) throw new ApiError(response.status, body.error.type, body.error.message, body.error.request_id)
  throw new ApiError(response.status, 'unexpected', `The service answered with status ${response.status}.`, requestId)
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined })

// A type alias, not an interface, so it can be passed where query parameters are expected.
export type Paging = {
  limit?: number
  offset?: number
}

export const api = {
  summary: (owner?: string) => request<Summary>(`/summary${query({ owner })}`),

  jobs: (params: Paging & { stage?: string; owner?: string; q?: string; sort?: JobSort; order?: Order }) =>
    request<ListResponse<JobSummary>>(`/jobs${query(params)}`),
  job: (jobNumber: string, revenue: RevenueBasis, cost: CostBasis) =>
    request<JobDetail>(`/jobs/${jobNumber}${query({ revenue, cost })}`),

  lines: (
    params: Paging & {
      kind: 'customer_invoice' | 'vendor_bill'
      owner?: string
      status?: string
      no_job?: string
      balance?: string
    },
  ) =>
    request<ListResponse<Line>>(`/lines${query(params)}`),

  issues: (
    params: Paging & {
      type?: string
      owner?: string
      status?: string
      severity?: string
      sort?: IssueSort
      order?: Order
    },
  ) =>
    request<ListResponse<Issue>>(`/issues${query(params)}`),
  issue: (id: number) => request<IssueDetail>(`/issues/${id}`),
  actOnIssue: (id: number, body: IssueUpdate) => post<IssueDetail>(`/issues/${id}/actions`, body),
  people: () => request<Person[]>('/people'),

  issueTypes: () => request<IssueType[]>('/issue-types'),
  updateIssueType: (key: string, body: { enabled?: boolean; tolerance?: string }) =>
    request<IssueType>(`/issue-types/${key}`, { method: 'PATCH', body: JSON.stringify(body) }),

  latestSync: () => request<ListResponse<SyncRun>>('/sync-runs?limit=1'),
  runSync: () => post<SyncRun>('/sync-runs'),

  ask: (body: { question: string; asked_by: string; owner?: string }) => post<AskResponse>('/ask', body),
  askHistory: (askedBy: string) => request<AskResponse[]>(`/ask/history${query({ asked_by: askedBy })}`),
  clearAskHistory: (askedBy: string) => request<void>(`/ask/history${query({ asked_by: askedBy })}`, { method: 'DELETE' }),

  sourceRecord: (id: number) => request<SourceRecord>(`/source-records/${id}`),
}
