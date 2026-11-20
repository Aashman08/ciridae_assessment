import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Copy, X } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import type { Coding, Draft, Issue } from '../lib/api'
import { suggestionsFor, useAssistant, usePage } from '../lib/assistant'
import { useConversation } from '../lib/conversation'
import { money } from '../lib/format'
import { useViewer } from '../lib/viewer'
import { Composer, Messages, Working } from './Conversation'
import { Button, ErrorNote } from './ui'

const ICON = { size: '1rem', strokeWidth: 1.5, 'aria-hidden': true } as const

const TITLES = { chat: 'Ask AI', draft: 'Follow-up draft', coding: 'Which job is this bill for' } as const

/** The assistant, asked from whatever page is open. It is told which page that is. */
function Chat() {
  const { viewer } = useViewer()
  const { page, label } = usePage()
  const conversation = useConversation()
  const { saved, failed, busy, clear } = conversation

  return (
    <>
      <div className="flex items-center justify-between gap-3 border-b border-hair px-4 py-2 text-[0.8125rem]">
        <p className="min-w-0 truncate text-ink-2">
          Looking at <span className="text-ink">{label}</span>
        </p>
        {saved.length + failed.length > 0 && (
          <button
            type="button"
            disabled={clear.isPending || busy}
            onClick={() => clear.mutate()}
            className="shrink-0 text-muted transition-colors duration-150 ease-out hover:text-ink disabled:opacity-50"
          >
            {clear.isPending ? 'Clearing' : 'Clear conversation'}
          </button>
        )}
      </div>
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-4">
        <Messages
          conversation={conversation}
          suggestions={suggestionsFor(page, Boolean(viewer.owner))}
          onSuggest={(question) => conversation.send(question, page)}
        />
      </div>
      <Composer conversation={conversation} page={page} placeholder="Ask about what is on this page" className="px-4 pt-2 pb-4" />
    </>
  )
}

/** The issue a draft or a suggestion is about, so the pane makes sense on its own. */
function About({ issue }: { issue: Issue }) {
  return (
    <p className="text-[0.8125rem] text-ink-2">
      <Link to={`/issues/${issue.id}`} className="text-ink hover:underline">
        {issue.title}
      </Link>
      {issue.document && <span className="font-mono text-xs"> {issue.document}</span>}
      {Number(issue.amount) > 0 && <span className="font-mono text-xs"> {money(issue.amount)}</span>}
    </p>
  )
}

/** A message for the person to read, change and send themselves. Nothing leaves the app. */
function DraftPreview({ issue }: { issue: Issue }) {
  const { viewer } = useViewer()
  const client = useQueryClient()
  const [copied, setCopied] = useState(false)

  const draft = useQuery({
    queryKey: ['draft', issue.id, viewer.name],
    queryFn: () => api.draftFollowUp(issue.id, viewer.name),
    // A draft is kept for the visit. A new one is written only when asked for.
    staleTime: Infinity,
    gcTime: Infinity,
  })

  const logged = useMutation({
    mutationFn: (message: Draft) =>
      api.actOnIssue(issue.id, {
        action: 'update',
        actor: viewer.name,
        note: `Sent a follow-up to ${message.recipient.name}: ${message.subject}`,
      }),
    onSuccess: () => client.invalidateQueries({ predicate: (query) => query.queryKey[0] !== 'draft' }),
  })

  async function copy(message: Draft) {
    await navigator.clipboard.writeText(`Subject: ${message.subject}\n\n${message.body}`)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-4">
      <div className="flex flex-col gap-4">
        <About issue={issue} />
        {draft.isFetching ? (
          <Working label="Writing a draft from the records" />
        ) : draft.isError ? (
          <ErrorNote error={draft.error} />
        ) : draft.data ? (
          <>
            <article className="flex flex-col rounded-xl border border-hair bg-card shadow-lift">
              <dl className="grid grid-cols-[4rem_minmax(0,1fr)] gap-x-3 gap-y-2 border-b border-hair p-4 text-[0.8125rem]">
                <dt className="text-ink-2">To</dt>
                <dd>{draft.data.recipient.name}</dd>
                <dt className="text-ink-2">Address</dt>
                <dd className={draft.data.recipient.email ? 'break-all' : 'text-accent-ink'}>
                  {draft.data.recipient.email ?? 'None on file'}
                </dd>
                <dt className="text-ink-2">Why them</dt>
                <dd className="text-ink-2">{draft.data.recipient.role}</dd>
                <dt className="text-ink-2">Subject</dt>
                <dd className="font-medium">{draft.data.subject}</dd>
              </dl>
              <p className="p-4 whitespace-pre-wrap">{draft.data.body}</p>
            </article>

            {draft.data.warnings.length > 0 && (
              <div className="text-[0.8125rem]">
                <p className="font-medium text-accent-ink">Check before sending</p>
                <ul className="mt-1 flex list-disc flex-col gap-1 pl-5 text-ink-2">
                  {draft.data.warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              </div>
            )}

            <div className="flex flex-wrap gap-2">
              <Button variant="primary" onClick={() => copy(draft.data)}>
                {copied ? <Check {...ICON} /> : <Copy {...ICON} />}
                {copied ? 'Copied' : 'Copy message'}
              </Button>
              <Button disabled={logged.isPending || logged.isSuccess} onClick={() => logged.mutate(draft.data)}>
                {logged.isSuccess ? 'Logged on the issue' : logged.isPending ? 'Logging' : 'Log that I sent it'}
              </Button>
              <Button onClick={() => draft.refetch()}>Draft again</Button>
            </div>
            {logged.isError && <p className="text-[0.8125rem] text-neg">{logged.error.message}</p>}
            <p className="text-xs leading-4 text-muted">
              Nothing is sent from here. Every figure in the draft is checked against the records for this issue as of the
              last sync. Copy it into your own email, change what you like, and log it once it has gone
            </p>
          </>
        ) : null}
      </div>
    </div>
  )
}

const CONFIDENCE = { high: 'High confidence', medium: 'Medium confidence', low: 'Low confidence' } as const

const LOOKUPS: Record<string, string> = {
  the_bill: 'Read the bill and the email it arrived on',
  vendor_history: "Read this vendor's other bills",
  candidate_jobs: 'Listed the jobs it could belong to',
  job_work: 'Looked at what a job has been spending on',
}

/** The agent's suggestion for an unassigned bill. A person accepts or rejects it. */
function CodingSuggestion({ issue }: { issue: Issue }) {
  const { viewer } = useViewer()
  const client = useQueryClient()
  const { close } = useAssistant()

  const suggestion = useQuery({
    queryKey: ['coding', issue.id],
    queryFn: async () => {
      const result = await api.suggestJob(issue.id)
      // The suggestion is written into the issue's history, so that needs reading again.
      void client.invalidateQueries({ queryKey: ['issue', issue.id] })
      return result
    },
    staleTime: Infinity,
    gcTime: Infinity,
  })

  const decide = useMutation({
    mutationFn: ({ accept, result }: { accept: boolean; result: Coding }) => {
      const what = result.decision === 'job' ? `job ${result.job_number} (${result.job_name})` : 'not a job cost'
      return api.actOnIssue(issue.id, {
        action: accept ? 'resolve' : 'update',
        actor: viewer.name,
        note: accept
          ? `Accepted the assistant's suggestion: ${what}. The bill still has to be changed in accounting.`
          : `Rejected the assistant's suggestion: ${what}.`,
      })
    },
    onSuccess: async () => {
      await client.invalidateQueries({ predicate: (query) => query.queryKey[0] !== 'coding' })
      close()
    },
  })

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-4">
      <div className="flex flex-col gap-4">
        <About issue={issue} />
        {suggestion.isFetching ? (
          <Working label="Reading the bill and comparing it with the jobs" />
        ) : suggestion.isError ? (
          <ErrorNote error={suggestion.error} />
        ) : suggestion.data ? (
          <>
            <article className="flex flex-col gap-3 rounded-xl border border-hair bg-card p-4 shadow-lift">
              <div>
                <p className="text-[0.8125rem] text-ink-2">
                  {suggestion.data.decision === 'job'
                    ? 'Suggested job'
                    : suggestion.data.decision === 'not_a_job_cost'
                      ? 'Suggestion'
                      : 'No suggestion'}
                </p>
                {suggestion.data.decision === 'job' ? (
                  <p className="mt-1 font-medium">
                    <Link to={`/jobs/${suggestion.data.job_number}`} className="hover:underline">
                      {suggestion.data.job_name}
                    </Link>
                    <span className="font-mono text-xs font-normal text-ink-2"> {suggestion.data.job_number}</span>
                  </p>
                ) : (
                  <p className="mt-1 font-medium">
                    {suggestion.data.decision === 'not_a_job_cost'
                      ? 'This is not a job cost'
                      : 'Not sure which job this belongs to'}
                  </p>
                )}
                <p className={`mt-1 text-[0.8125rem] ${suggestion.data.confidence === 'high' ? 'text-ink-2' : 'text-accent-ink'}`}>
                  {CONFIDENCE[suggestion.data.confidence]}
                </p>
              </div>

              <div>
                <p className="text-[0.8125rem] text-ink-2">Why</p>
                <ul className="mt-1 flex list-disc flex-col gap-1 pl-5">
                  {suggestion.data.reasons.map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
              </div>

              {suggestion.data.runner_up && (
                <div>
                  <p className="text-[0.8125rem] text-ink-2">
                    {suggestion.data.decision === 'job' ? 'Also considered' : 'Closest fit'}
                  </p>
                  <p className="mt-1">
                    <Link to={`/jobs/${suggestion.data.runner_up.job_number}`} className="hover:underline">
                      {suggestion.data.runner_up.job_name}
                    </Link>
                    <span className="font-mono text-xs text-ink-2"> {suggestion.data.runner_up.job_number}</span>
                  </p>
                </div>
              )}

              <details className="text-[0.8125rem] text-ink-2">
                <summary className="cursor-pointer text-xs leading-4 text-muted">
                  {suggestion.data.looked_at.length} {suggestion.data.looked_at.length === 1 ? 'lookup' : 'lookups'}
                </summary>
                <ol className="flex flex-col gap-1 pt-2">
                  {suggestion.data.looked_at.map((step, index) => (
                    <li key={index}>
                      {LOOKUPS[step.tool] ?? step.tool}
                      {typeof step.arguments.job_number === 'string' && (
                        <span className="font-mono text-xs text-muted"> {step.arguments.job_number}</span>
                      )}
                    </li>
                  ))}
                </ol>
              </details>
            </article>

            <div className="flex flex-wrap gap-2">
              {suggestion.data.decision !== 'unsure' && (
                <>
                  <Button
                    variant="primary"
                    disabled={decide.isPending}
                    onClick={() => decide.mutate({ accept: true, result: suggestion.data })}
                  >
                    Accept and resolve
                  </Button>
                  <Button disabled={decide.isPending} onClick={() => decide.mutate({ accept: false, result: suggestion.data })}>
                    Reject
                  </Button>
                </>
              )}
              <Button disabled={decide.isPending} onClick={() => suggestion.refetch()}>
                Try again
              </Button>
            </div>
            {decide.isError && <p className="text-[0.8125rem] text-neg">{decide.error.message}</p>}
            <p className="text-xs leading-4 text-muted">
              {suggestion.data.decision === 'unsure'
                ? 'The assistant would not guess. Use Log update on the issue once you know where the bill belongs'
                : 'Accepting records your decision and resolves the issue. The bill itself is only changed in accounting'}
            </p>
          </>
        ) : null}
      </div>
    </div>
  )
}

/** The pane beside the page: the assistant, a drafted message, or a suggestion for a bill. */
export function AssistantPane() {
  const { view, close } = useAssistant()
  if (!view) return null

  return (
    <aside
      aria-label={TITLES[view.kind]}
      className="fixed inset-y-0 right-0 z-30 flex w-full flex-col border-l border-hair bg-bg shadow-float sm:w-[26rem] 2xl:sticky 2xl:top-0 2xl:z-auto 2xl:h-dvh 2xl:w-auto 2xl:shadow-none"
    >
      <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-hair px-4">
        <h2 className="font-medium">{TITLES[view.kind]}</h2>
        <button
          type="button"
          aria-label="Close"
          onClick={close}
          className="grid size-8 place-items-center rounded-lg text-muted transition-colors duration-150 ease-out hover:bg-raised hover:text-ink"
        >
          <X {...ICON} />
        </button>
      </header>
      {view.kind === 'chat' && <Chat />}
      {/* Keyed on the issue so each one gets its own draft or suggestion. */}
      {view.kind === 'draft' && <DraftPreview key={view.issue.id} issue={view.issue} />}
      {view.kind === 'coding' && <CodingSuggestion key={view.issue.id} issue={view.issue} />}
    </aside>
  )
}
