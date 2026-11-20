import { ArrowUp, LoaderCircle } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import type { AskPage, AskResponse, AskStep } from '../lib/api'
import { sourceLink } from '../lib/assistant'
import type { Conversation } from '../lib/conversation'
import { dateTime, longDate } from '../lib/format'
import { cx } from '../lib/styles'
import { AnswerView } from './AnswerView'
import { Button, ErrorNote } from './ui'

// What each fixed tool does, in the words a reader would use.
const STEPS: Record<string, string> = {
  company_summary: 'Read the totals',
  list_jobs: 'Listed jobs',
  get_job: 'Opened a job',
  list_issues: 'Listed issues',
  get_issue: 'Opened an issue',
  list_issue_types: 'Read what each issue type means',
  list_invoices: 'Listed customer invoices',
  list_vendor_bills: 'Listed vendor bills',
  owed_by_customer: 'Totalled what each customer owes',
  totals_by_month: 'Totalled invoices or bills by month',
}

const ICON = { size: '1rem', strokeWidth: 1.5, 'aria-hidden': true } as const

function Inputs({ step }: { step: AskStep }) {
  const entries = Object.entries(step.arguments)
  if (entries.length === 0) return null
  return <span className="font-mono text-xs text-muted"> {entries.map(([key, value]) => `${key}: ${String(value)}`).join(', ')}</span>
}

/** Shown wherever work is actually in progress, and nowhere else. */
export function Working({ label }: { label: string }) {
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

/** What came back: on the left, with how it was worked out underneath. */
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

interface MessagesProps {
  conversation: Conversation
  /** Offered while the conversation is empty. */
  suggestions: string[]
  onSuggest: (question: string) => void
}

/** The conversation so far, oldest first, kept scrolled to the newest message. */
export function Messages({ conversation, suggestions, onSuggest }: MessagesProps) {
  const { history, saved, failed, waiting, count } = conversation
  const end = useRef<HTMLDivElement>(null)

  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' })
  }, [count])

  return (
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
                <Button className="h-auto! py-2 text-left whitespace-normal!" onClick={() => onSuggest(question)}>
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
  )
}

interface ComposerProps {
  conversation: Conversation
  page?: AskPage
  placeholder?: string
  className?: string
}

/** Where a question is typed. It stays at the bottom, however long the conversation gets. */
export function Composer({ conversation, page, placeholder = 'Ask about jobs, invoices, bills or issues', className }: ComposerProps) {
  const [draft, setDraft] = useState('')
  const { busy } = conversation

  function submit(event: FormEvent) {
    event.preventDefault()
    if (!draft.trim() || busy) return
    conversation.send(draft, page)
    setDraft('')
  }

  return (
    <form onSubmit={submit} className={cx('bg-bg', className)}>
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
          placeholder={placeholder}
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
  )
}
