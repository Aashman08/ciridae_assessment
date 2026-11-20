import { createContext, useContext } from 'react'
import { useLocation, useSearchParams } from 'react-router-dom'
import type { AskPage, AskSource, Item } from './api'

/** What the side pane is showing. It is closed when this is null. */
export type AssistantView =
  | { kind: 'chat' }
  | { kind: 'draft'; item: Item }
  | { kind: 'coding'; item: Item }
  /** An invoice or vendor bill laid out as a document. */
  | { kind: 'document'; lineId: number; documentKind: 'customer_invoice' | 'vendor_bill' }

export const AssistantContext = createContext<{
  view: AssistantView | null
  show: (view: AssistantView) => void
  close: () => void
} | null>(null)

export function useAssistant() {
  const value = useContext(AssistantContext)
  if (!value) throw new Error('useAssistant needs an AssistantProvider above it')
  return value
}

const LISTS: Record<string, AskPage['kind']> = {
  jobs: 'jobs',
  issues: 'issues',
  invoices: 'invoices',
  bills: 'bills',
  'issue-types': 'issue_types',
}

// The filters worth telling the assistant about. Paging and sorting are not.
const FILTERS = ['stage', 'q', 'status', 'severity', 'type', 'owner', 'balance', 'no_job']

/** The page someone is on, as the assistant is told about it, and how to say it to them. */
export function usePage(): { page: AskPage; label: string } {
  const { pathname } = useLocation()
  const [params] = useSearchParams()
  const [, first, second] = pathname.split('/')

  if (first === 'jobs' && second) return { page: { kind: 'job', job_number: second.toUpperCase() }, label: `Job ${second.toUpperCase()}` }

  const kind = LISTS[first] ?? 'overview'
  const filters: Record<string, string> = {}
  for (const key of FILTERS) {
    const value = params.get(key)
    if (value) filters[key] = value.slice(0, 60)
  }
  const names: Record<AskPage['kind'], string> = {
    overview: 'Overview',
    jobs: 'Jobs',
    job: 'Job',
    issues: 'Issues',
    issue: 'Issue',
    invoices: 'Customer invoices',
    bills: 'Vendor bills',
    issue_types: 'Issue types',
  }
  const filtered = Object.keys(filters).length > 0
  return { page: { kind, filters }, label: filtered ? `${names[kind]}, as filtered` : names[kind] }
}

/** Questions that make sense from where the person is. */
export function suggestionsFor(page: AskPage, ownJobsOnly: boolean): string[] {
  if (page.kind === 'job') {
    return ['What is wrong with this job?', 'What did this job make, by ledger cost and by ops log cost?', 'What is still owed on this job?']
  }
  if (page.kind === 'invoices') return ['Which invoices are most overdue?', 'Chart invoicing by month', 'Which customers owe the most?']
  if (page.kind === 'bills') return ['Which bills have no job?', 'Which bills are waiting on approval?', 'Chart vendor bills by month']
  if (page.kind === 'issues') return ['What should be dealt with first?', 'Which issues are about the same invoice or bill?']
  if (page.kind === 'jobs') return ['Which jobs have the lowest margin?', 'Which closed jobs still have unpaid vendor bills?']
  return ownJobsOnly
    ? ['What should I chase first?', 'How much do customers owe on my jobs?']
    : ['Which customers owe us the most, and how much of it is past due?', 'Which invoices have been approved but never sent?']
}

/** Where a source leads. An invoice or bill opens the job it belongs to. */
export function sourceLink(source: AskSource): string | null {
  if (source.kind === 'issue') return `/issues/${source.id}`
  return source.id ? `/jobs/${source.id}` : null
}
