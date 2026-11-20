import { useMutation, useMutationState, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowUp, ChevronDown, FileText, HardHat, LoaderCircle, Receipt, TriangleAlert, X } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { AnswerView } from '../components/AnswerView'
import { Button, ErrorNote } from '../components/ui'
import { api, ApiError } from '../lib/api'
import type { AskResponse, AskSource, AskStep } from '../lib/api'
import { dateTime, longDate } from '../lib/format'
import { useViewer } from '../lib/viewer'

// What each fixed tool does, in the words a reader would use.
const STEPS: Record<string, string> = {
  company_summary: 'Read the totals',
  list_jobs: 'Listed jobs',
  get_job: 'Opened a job',
  list_issues: 'Listed issues',
  list_issue_types: 'Read what each issue type means',
  list_invoices: 'Listed customer invoices',
  list_vendor_bills: 'Listed vendor bills',
  owed_by_customer: 'Totalled what each customer owes',
  totals_by_month: 'Totalled invoices or bills by month',
}

const EVERY_JOB = [
  'Which customers owe us the most, and how much of it is past due?',
  'Which closed jobs still have unpaid vendor bills?',
  'What did the Redbird dock rebuild make, by ledger and by ops log cost?',
  'Which invoices have been approved but never sent?',
]
const OWN_JOBS = [
  'What should I chase first?',
  'Which of my jobs have costs that disagree between ops and the ledger?',
  'Which bills are waiting on me, and do any have a discount deadline?',
  'How much do customers owe on my jobs?',
]

const ICON = { size: '1rem', strokeWidth: 1.5, 'aria-hidden': true } as const

const SOURCES_OPEN = 'ask-sources-open'

const SOURCE_KINDS: Record<AskSource['kind'], { icon: LucideIcon; name: string }> = {
  job: { icon: HardHat, name: 'Job' },
  issue: { icon: TriangleAlert, name: 'Issue' },
  invoice: { icon: Receipt, name: 'Customer invoice' },
  vendor_bill: { icon: FileText, name: 'Vendor bill' },
}

function sourceLink(source: AskSource): string | null {
  if (source.kind === 'issue') return `/issues/${source.id}`
  // An invoice or bill opens the job it belongs to. One with no job has nowhere to go.
  return source.id ? `/jobs/${source.id}` : null
}

/** A source's two lines: what it is called, then what kind of record it is and its number. */
function describe(source: AskSource): { title: string; detail: string } {
  const kind = SOURCE_KINDS[source.kind].name
  if (source.kind === 'job') {
    // A job's label is its number followed by its name.
    const [number, ...name] = source.label.split(' ')
    return { title: name.join(' ') || number, detail: `${kind} ${number}` }
  }
  if (source.kind === 'issue') return { title: source.label, detail: kind }
  return { title: source.label, detail: source.id ? `${kind} on job ${source.id}` : `${kind}, no job` }
}

/** Every record the conversation's answers rest on, newest answer first, each listed once. */
function conversationSources(exchanges: AskResponse[]): AskSource[] {
  const seen = new Map<string, AskSource>()
  for (const exchange of [...exchanges].reverse()) {
    for (const source of exchange.sources) {
      const key = `${source.kind}:${source.label}`
      if (!seen.has(key)) seen.set(key, source)
    }
  }
  return [...seen.values()]
}

/** Whether the sources panel is showing. Closed until asked for, then remembered between visits. */
function useSourcesOpen(): [boolean, () => void] {
  const [open, setOpen] = useState(() => {
    try {
      return localStorage.getItem(SOURCES_OPEN) === 'yes'
    } catch {
      return false
    }
  })

  function toggle() {
    setOpen(!open)
    try {
      localStorage.setItem(SOURCES_OPEN, open ? 'no' : 'yes')
    } catch {
      // Storage can be blocked. The choice then lasts until the page reloads.
    }
  }

  return [open, toggle]
}

/** The records behind the answers, as a list. It is only on the page while the dropdown is open. */
function Sources({ sources, onClose, className }: { sources: AskSource[]; onClose: () => void; className: string }) {
  return (
    <aside aria-label="Sources" className={`rounded-xl border border-hair bg-card p-2 shadow-lift ${className}`}>
      <div className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-3 py-1 pr-1 pl-3">
        <h2 className="font-medium">Sources</h2>
        <span className="font-mono text-xs text-muted">{sources.length || ''}</span>
        <button
          type="button"
          aria-label="Close sources"
          onClick={onClose}
          className="grid size-8 place-items-center rounded-lg text-muted transition-colors duration-150 ease-out hover:bg-raised hover:text-ink"
        >
          <X {...ICON} />
        </button>
      </div>
      {sources.length === 0 ? (
        <p className="px-3 pt-1 pb-3 text-[0.8125rem] text-muted">
          The jobs, invoices, bills and issues an answer rests on are listed here, with a link to each
        </p>
      ) : (
        <ul className="flex flex-col gap-0.5 pt-1">
          {sources.map((source) => {
            const { icon: Icon } = SOURCE_KINDS[source.kind]
            const { title, detail } = describe(source)
            const to = sourceLink(source)
            const row = 'grid grid-cols-[1rem_minmax(0,1fr)] items-start gap-x-3 rounded-lg px-3 py-2'
            const body = (
              <>
                <Icon {...ICON} className="mt-0.5 text-muted" />
                <span className="min-w-0">
                  <span className="block text-[0.8125rem]">{title}</span>
                  <span className="block font-mono text-xs leading-4 text-muted">{detail}</span>
                </span>
              </>
            )
            return (
              <li key={`${source.kind}:${source.label}`}>
                {to ? (
                  <Link to={to} className={`${row} transition-colors duration-150 ease-out hover:bg-raised`}>
                    {body}
                  </Link>
                ) : (
                  <span className={row}>{body}</span>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </aside>
  )
}

function Inputs({ step }: { step: AskStep }) {
  const entries = Object.entries(step.arguments)
  if (entries.length === 0) return null
  return <span className="font-mono text-xs text-muted"> {entries.map(([key, value]) => `${key}: ${String(value)}`).join(', ')}</span>
}

/** Shown wherever work is actually in progress, and nowhere else. */
function Working({ label }: { label: string }) {
  return (
    <p role="status" className="flex items-center gap-2 text-ink-2">
      <LoaderCircle {...ICON} className="animate-spin" />
      {label}
    </p>
  )
}

/** What the person typed: a bubble on the right, as in any chat. */
function Question({ text, askedAt }: { text: string; askedAt?: string }) {
  return (
    <div className="flex justify-end">
      <p
        className="max-w-[85%] rounded-2xl rounded-br-md bg-raised px-4 py-2 whitespace-pre-wrap ring-1 ring-hair ring-inset"
        title={askedAt ? dateTime(askedAt) : undefined}
      >
        {text}
      </p>
    </div>
  )
}

/** What came back: plain text on the left, with how it was worked out underneath. */
function Answer({ response }: { response: AskResponse }) {
  // A table row that names one of the answer's sources opens it.
  const links: Record<string, string> = {}
  for (const source of response.sources) {
    const to = sourceLink(source)
    if (to && source.kind !== 'issue') links[source.kind === 'job' ? source.id : source.label] = to
  }

  return (
    <div className="flex flex-col gap-3">
      <AnswerView spec={response.spec} links={links} />

      {response.worked_out.length > 0 && (
        <p className="text-[0.8125rem] text-ink-2">
          Calculated by the assistant from the figures it looked up, not read directly from the data:{' '}
          <span className="font-mono text-xs text-accent-ink">{response.worked_out.join('  ')}</span>
        </p>
      )}

      {/* The reader can see exactly which fixed lookups produced the answer. */}
      <details className="text-[0.8125rem] text-ink-2">
        <summary className="cursor-pointer text-xs leading-4 text-muted">
          {response.steps.length} {response.steps.length === 1 ? 'lookup' : 'lookups'}, {response.sources.length}{' '}
          {response.sources.length === 1 ? 'source' : 'sources'}, figures as of {longDate(response.as_of)}
        </summary>
        {response.steps.length === 0 ? (
          <p className="pt-2">No lookup was needed, so this answer contains no figures from the data</p>
        ) : (
          <ol className="flex flex-col gap-1 pt-2">
            {response.steps.map((step, index) => (
              <li key={index}>
                {STEPS[step.tool] ?? step.tool}
                <Inputs step={step} />
              </li>
            ))}
          </ol>
        )}
      </details>
    </div>
  )
}

export function Ask() {
  const { viewer } = useViewer()
  const client = useQueryClient()
  const [draft, setDraft] = useState('')
  const end = useRef<HTMLDivElement>(null)
  const [sourcesOpen, toggleSources] = useSourcesOpen()

  const historyKey = ['ask-history', viewer.name]
  const askKey = ['ask', viewer.name]

  // The conversation is kept on the server, per person, so it is still here
  // after changing page, reloading, or coming back tomorrow.
  const history = useQuery({ queryKey: historyKey, queryFn: () => api.askHistory(viewer.name) })

  const ask = useMutation({
    mutationKey: askKey,
    mutationFn: (question: string) => api.ask({ question, asked_by: viewer.name, owner: viewer.owner }),
    // Runs even if this page has been left, so the answer is waiting on return.
    onSuccess: () => client.invalidateQueries({ queryKey: historyKey }),
  })

  // Questions still being answered, and ones that failed, read from the shared
  // cache and not from this component. That is what lets a question outlive the page.
  const waiting = useMutationState({
    filters: { mutationKey: askKey, status: 'pending' },
    select: (mutation) => ({ id: mutation.mutationId, question: mutation.state.variables as string }),
  })
  const failed = useMutationState({
    filters: { mutationKey: askKey, status: 'error' },
    select: (mutation) => ({
      id: mutation.mutationId,
      question: mutation.state.variables as string,
      error: mutation.state.error instanceof ApiError ? mutation.state.error.message : 'The question could not be sent.',
    }),
  })

  const clear = useMutation({
    mutationFn: () => api.clearAskHistory(viewer.name),
    onSuccess: () => {
      const cache = client.getMutationCache()
      cache.findAll({ mutationKey: askKey }).forEach((mutation) => cache.remove(mutation))
      return client.invalidateQueries({ queryKey: historyKey })
    },
  })

  const busy = waiting.length > 0

  function send(question: string) {
    const text = question.trim()
    if (!text || busy) return
    setDraft('')
    ask.mutate(text)
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    send(draft)
  }

  const saved = history.data ?? []
  const count = saved.length + failed.length + waiting.length
  const sources = conversationSources(saved)

  // Keep the newest message in view as the conversation grows.
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' })
  }, [count])

  const suggestions = viewer.owner ? OWN_JOBS : EVERY_JOB

  return (
    // The conversation has the page to itself, in a reading-width column as chat does.
    // The page only splits to make room for the sources while they are open.
    <div className={`grid grid-cols-1 items-start gap-6 ${sourcesOpen ? 'xl:grid-cols-[minmax(0,1fr)_20rem]' : ''}`}>
      <div className="mx-auto flex min-h-[calc(100vh-11rem)] w-full max-w-[48rem] flex-col">
        <header className={`flex flex-wrap items-center gap-4 pb-6 ${count === 0 ? 'justify-between' : 'justify-end'}`}>
          {/* The introduction is for an empty page. Once there is a conversation it only takes up room. */}
          {count === 0 ? (
            <div className="min-w-[16rem] flex-1">
              <h1 className="text-xl leading-7 font-medium">Ask</h1>
              <p className="text-[0.8125rem] text-ink-2">
                Answers come from {viewer.owner ? 'your jobs' : 'every job'}. It can look things up but cannot change anything
              </p>
            </div>
          ) : (
            <h1 className="sr-only">Ask</h1>
          )}
          <div className="flex shrink-0 flex-wrap gap-2">
            {saved.length + failed.length > 0 && (
              <Button disabled={clear.isPending || busy} onClick={() => clear.mutate()}>
                {clear.isPending ? 'Clearing' : 'Clear conversation'}
              </Button>
            )}
            <Button aria-expanded={sourcesOpen} onClick={toggleSources}>
              Sources
              {sources.length > 0 && <span className="font-mono text-xs text-muted">{sources.length}</span>}
              <ChevronDown
                {...ICON}
                className={`text-muted transition-transform duration-150 ease-out ${sourcesOpen ? 'rotate-180' : ''}`}
              />
            </Button>
          </div>
        </header>

        {/* On a narrow window there is no room beside the conversation, so the sources open under the button. */}
        {sourcesOpen && <Sources sources={sources} onClose={toggleSources} className="mb-6 xl:hidden" />}

        <div className="flex flex-1 flex-col gap-6">
          {history.isPending ? (
            <Working label="Loading your conversation" />
          ) : history.isError ? (
            <ErrorNote error={history.error} />
          ) : count === 0 ? (
            <div className="flex flex-col gap-3">
              <p className="text-ink-2">Try one of these, or type your own below</p>
              <ul className="flex flex-col items-start gap-2">
                {suggestions.map((question) => (
                  <li key={question}>
                    <Button className="h-auto! py-2 text-left whitespace-normal!" onClick={() => send(question)}>
                      {question}
                    </Button>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <>
              {saved.map((exchange) => (
                <div key={exchange.id} className="flex flex-col gap-4">
                  <Question text={exchange.question} askedAt={exchange.created_at} />
                  <Answer response={exchange} />
                </div>
              ))}
              {failed.map((attempt) => (
                <div key={`failed-${attempt.id}`} className="flex flex-col gap-4">
                  <Question text={attempt.question} />
                  <p className="text-ink-2">{attempt.error}</p>
                </div>
              ))}
              {waiting.map((attempt) => (
                <div key={`waiting-${attempt.id}`} className="flex flex-col gap-4">
                  <Question text={attempt.question} />
                  <Working label="Looking this up in your data" />
                </div>
              ))}
            </>
          )}
          <div ref={end} />
        </div>

        {/* The composer stays at the bottom of the window, however long the conversation gets. */}
        <form onSubmit={submit} className="sticky bottom-0 z-20 mt-6 bg-bg pt-2 pb-4">
          <div className="flex items-center gap-2 rounded-2xl border border-hair bg-card p-2 shadow-lift">
            <label htmlFor="ask-question" className="sr-only">
              Your question
            </label>
            <input
              id="ask-question"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              maxLength={1000}
              autoComplete="off"
              placeholder="Ask about jobs, invoices, bills or issues"
              className="h-8 min-w-0 flex-1 bg-transparent px-2 outline-none placeholder:text-muted"
            />
            <Button
              variant="primary"
              type="submit"
              className="size-8 rounded-full! px-0!"
              aria-label={busy ? 'Working' : 'Send'}
              disabled={!draft.trim() || busy}
            >
              {busy ? <LoaderCircle {...ICON} className="animate-spin" /> : <ArrowUp {...ICON} />}
            </Button>
          </div>
        </form>
      </div>

      {sourcesOpen && <Sources sources={sources} onClose={toggleSources} className="sticky top-6 hidden xl:block" />}
    </div>
  )
}
