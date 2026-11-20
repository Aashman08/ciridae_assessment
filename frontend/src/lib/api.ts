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

/** Something the app can start: a drafted message, a bill coding, an assignment, a date or a dismissal. */
export interface ItemAction {
  key: 'message_customer' | 'message_colleague' | 'code_bill' | 'assign_ops_manager' | 'wait' | 'dismiss'
  /** What the button says, such as "Chase the customer". */
  label: string
}

/**
 * One thing a person fixes: an invoice, a bill, or a gap on a job. The checks
 * that fired on it are its tags.
 */
export interface Item {
  /** Stable name: the kind and what it is about, such as "bill_stuck:APX-40766". */
  key: string
  kind:
    | 'invoice_unpaid'
    | 'invoice_not_sent'
    | 'bill_stuck'
    | 'bill_no_job'
    | 'cost_gap'
    | 'billing_gap'
    | 'late_start'
    | 'stalled'
    | 'budget_risk'
    | 'no_ops_manager'
  title: string
  document: string | null
  company: string | null
  job_number: string | null
  job_name: string | null
  amount: Money
  severity: 'high' | 'medium'
  tags: { key: string; label: string }[]
  due_on: string | null
  days_late: number | null
  owner: string
  owner_role: Issue['owner_role']
  state: 'needs_action' | 'waiting' | 'done'
  follow_up_on: string | null
  note_count: number
  /** What is wrong, one sentence for each check that fired. */
  details: string[]
  resolution_note: string | null
  checks: string[]
  issue_ids: number[]
  /** The work that fixes this kind of item, by fixed rule. */
  action: ItemAction
  /** What to do next: the rule, or the assistant's review when there is a current one. */
  suggestion: { action: ItemAction; reason: string | null; follow_up_on: string | null; by: 'rule' | 'assistant' }
  evidence: Line[]
  events: IssueEvent[]
  /** Notes on this invoice in accounting, written before it reached this app. */
  source_notes: { by: string; on: string; note: string }[]
}

/** A job and what needs fixing on it. `job_number` is null for bills that are on no job. */
export interface JobItems {
  job_number: string | null
  job_name: string | null
  ops_manager: string | null
  /** Unpaid or unsent on this job's flagged invoices and bills, each counted once. */
  flagged_amount: Money
  tags: { key: string; label: string }[]
  items: Item[]
  /** The one thing to do first. */
  suggestion: { item_key: string; action: ItemAction; reason: string | null; by: 'rule' | 'assistant' } | null
  /** When the assistant last reviewed these items. Null if it has not, or they have changed since. */
  reviewed_at: string | null
}

export interface ItemUpdate {
  action: 'update' | 'resolve' | 'dismiss' | 'reopen'
  actor: string
  note?: string
  assignee?: string
  follow_up_on?: string
  follow_up_in_working_days?: number
  clear_follow_up?: boolean
}

/** Someone an issue can belong to. */
/** Where an activity entry came from: a note in the project system or accounting, or something done in this app. */
export type ActivitySource = 'project' | 'accounting' | 'app'

/** One note or one action, newest first in any list of them. */
export interface ActivityEntry {
  at: string
  source: ActivitySource
  /** note, what happened to an issue (opened, resolved, dismissed…), or setting_changed */
  kind: string
  /** A person's name, or 'system' for a sync and 'assistant' for the assistant. */
  by: string
  text: string | null
  /** The check it concerns. */
  about: string | null
  job_number: string | null
  job_name: string | null
  document: string | null
}

export type CommitmentKind = 'payment_promised' | 'promised_to_customer' | 'waiting_on' | 'we_will'
export type CommitmentState = 'missed' | 'due_soon' | 'open' | 'kept' | 'done'

/** A promise or a wait the assistant found in a note, and where it stands, worked out from the records. */
export interface Commitment {
  id: number
  kind: CommitmentKind
  who: string
  what: string
  due_on: string | null
  state: CommitmentState
  job_number: string | null
  job_name: string | null
  document: string | null
  noted_by: string
  noted_on: string
  noted_in: 'project' | 'accounting'
  note: string
}

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
  /** What needs fixing on this job. Null when nothing is open. */
  items: JobItems | null
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
    /** The contract value split by how far it has got. The parts add up to the whole. */
    stages: {
      key: 'collected' | 'sent_not_collected' | 'invoiced_not_sent' | 'earned_not_invoiced' | 'not_yet_earned'
      amount: Money
      share_pct: string
    }[]
  }
  /** How many checks have fired and are still open. */
  open_issue_count: number
  /** How many things there are to fix. Several checks on one document count once. */
  open_item_count: number
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

/** What the person has on screen when they ask, so "this job" means something. */
export interface AskPage {
  kind: 'overview' | 'jobs' | 'job' | 'issues' | 'issue' | 'invoices' | 'bills' | 'issue_types'
  job_number?: string
  issue_id?: number
  filters?: Record<string, string>
}

/** A follow-up message for a person to read, change and send themselves. */
export interface Draft {
  recipient: {
    audience: 'customer' | 'internal'
    name: string
    role: string
    email: string | null
    /** People copied in, such as the person named on the invoice when that is someone else. */
    cc: { name: string; role: string; email: string | null }[]
  }
  subject: string
  body: string
  /** Things to check before sending, such as a figure that is not in the records. */
  warnings: string[]
  as_of: string
}

/** A suggestion for which job an unassigned vendor bill belongs to. */
export interface Coding {
  bill: string
  decision: 'job' | 'not_a_job_cost' | 'unsure'
  job_number: string | null
  job_name: string | null
  confidence: 'high' | 'medium' | 'low'
  reasons: string[]
  runner_up: { job_number: string; job_name: string } | null
  looked_at: AskStep[]
}

/** Whether jobs start quickly, keep moving, spend at the right pace, and have someone in charge. */
export interface Operations {
  as_of: string
  /** How a job is judged urgent. Nothing in the source marks it. */
  urgent_rule: string
  start_tolerance_days: number
  urgent: {
    job_number: string
    name: string
    urgent_reason: string
    incident_on: string | null
    won_on: string | null
    on_site_on: string | null
    days_damage_to_site: number | null
    days_win_to_site: number | null
    started_in_time: boolean
  }[]
  waiting: {
    job_number: string
    name: string
    ops_manager: string | null
    urgent_reason: string | null
    won_on: string | null
    on_site_on: string | null
    days_win_to_start: number | null
    slow: boolean
  }[]
  in_progress: {
    job_number: string
    name: string
    ops_manager: string | null
    on_site_on: string | null
    planned_finish_on: string | null
    time_gone_pct: string | null
    budget_used_pct: string | null
    last_work_on: string | null
    flags: ('past_finish' | 'no_activity' | 'budget_burn')[]
  }[]
  owners: {
    name: string
    jobs_in_progress: number
    jobs_not_started: number
    open_items: number
    needing_action: number
    schedule_items: number
  }[]
}

/** One week or month of the ledger, and the running totals from the first period to this one. */
export interface FinancePeriod {
  revenue: Money
  cost: Money
  invoiced: Money
  collected: Money
  revenue_to_date: Money
  cost_to_date: Money
  invoiced_to_date: Money
  collected_to_date: Money
}

/** The ledger's view of the business: what was earned and spent, where cost went, and what is owed. */
export interface Finance {
  as_of: string
  revenue: Money
  cost: Money
  profit: Money
  margin_pct: string | null
  by_month: (FinancePeriod & { month: string })[]
  /** The same figures a week at a time, from the Monday each week starts on. */
  by_week: (FinancePeriod & { week_of: string })[]
  /** What the project team logged under each cost code, and its share of all they logged. */
  cost_by_code: { cost_code: string; ops_cost: Money; share_pct: string }[]
  /** All cost the project teams logged. */
  logged_cost: Money
  /** The ledger accounts job cost is posted to. One account means the ledger cannot split cost by cost code. */
  ledger_cost_accounts: string[]
  receivables_by_age: { bucket: 'not_due' | 'late_1_30' | 'late_31_60' | 'late_over_60'; invoices: number; amount: Money }[]
  by_service_line: { service_line: string; jobs: number; revenue: Money; cost: Money; profit: Money; margin_pct: string | null }[]
}

export interface DocumentParty {
  name: string
  attention: string | null
  title: string | null
  email: string | null
  address: string[]
}

/** An invoice or vendor bill laid out from its records, as the paper copy would be. Not the original file. */
export interface Document {
  line_id: number
  kind: 'customer_invoice' | 'vendor_bill'
  number: string
  status: string | null
  issued_on: string | null
  due_on: string | null
  approved_on: string | null
  sent_on: string | null
  terms: string | null
  discount: string | null
  issuer: DocumentParty
  recipient: DocumentParty
  job_number: string | null
  job_name: string | null
  site: string[]
  lines: { description: string; quantity: string | null; unit_price: Money | null; amount: Money }[]
  subtotal: Money
  tax: Money
  total: Money
  paid: Money
  balance: Money
  payments: { on: string | null; amount: Money; method: string | null; reference: string | null }[]
  files: string[]
  received_by_email: string | null
  notes: string[]
  source_record_id: number
}

/** One of Harborstone's systems, as we last read it. */
export interface SourceSystem {
  system: 'crm' | 'project' | 'accounting'
  tables: number
  records: number
  last_read_at: string | null
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
  finance: () => request<Finance>('/finance'),
  operations: () => request<Operations>('/operations'),

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
  items: (params: { state?: string; owner?: string; type?: string }) =>
    request<{ groups: JobItems[]; item_count: number }>(`/items${query(params)}`),
  actOnItem: (key: string, body: ItemUpdate) => post<Item>(`/items/${encodeURIComponent(key)}/actions`, body),
  draftForItem: (key: string, writer: string) => post<Draft>(`/items/${encodeURIComponent(key)}/draft`, { writer }),
  reviewJob: (jobNumber: string) => post<JobItems>(`/jobs/${jobNumber}/review`),
  people: () => request<Person[]>('/people'),
  sources: () => request<SourceSystem[]>('/sources'),

  commitments: (params: Paging & { job?: string; owner?: string; kind?: CommitmentKind; state?: string }) =>
    request<ListResponse<Commitment>>(`/commitments${query(params)}`),
  actOnCommitment: (id: number, body: { action: 'done' | 'reopen'; actor: string }) => post<Commitment>(`/commitments/${id}/actions`, body),
  noteReading: () => request<{ unread: number; read: number }>('/notes/reading'),
  readNotes: () => post<{ notes_read: number; commitments_found: number }>('/notes/read'),

  activity: (params: Paging & { job?: string; owner?: string; person?: string; source?: string; kind?: string; people_only?: boolean }) =>
    request<ListResponse<ActivityEntry>>(`/activity${query(params)}`),

  issueTypes: () => request<IssueType[]>('/issue-types'),
  updateIssueType: (key: string, body: { enabled?: boolean; tolerance?: string; actor: string }) =>
    request<IssueType>(`/issue-types/${key}`, { method: 'PATCH', body: JSON.stringify(body) }),

  latestSync: () => request<ListResponse<SyncRun>>('/sync-runs?limit=1'),
  runSync: () => post<SyncRun>('/sync-runs'),

  ask: (body: { question: string; asked_by: string; owner?: string; page?: AskPage }) => post<AskResponse>('/ask', body),
  draftFollowUp: (issueId: number, writer: string) => post<Draft>(`/issues/${issueId}/draft`, { writer }),
  suggestJob: (issueId: number) => post<Coding>(`/issues/${issueId}/coding`),
  askHistory: (askedBy: string) => request<AskResponse[]>(`/ask/history${query({ asked_by: askedBy })}`),
  clearAskHistory: (askedBy: string) => request<void>(`/ask/history${query({ asked_by: askedBy })}`, { method: 'DELETE' }),

  document: (lineId: number) => request<Document>(`/lines/${lineId}/document`),
}
