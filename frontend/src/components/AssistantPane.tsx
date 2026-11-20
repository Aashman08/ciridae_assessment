import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Copy, RotateCcw, SendHorizontal, X } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import type { Coding, Draft, Item } from '../lib/api'
import { suggestionsFor, useAssistant, usePage } from '../lib/assistant'
import { useConversation } from '../lib/conversation'
import { money } from '../lib/format'
import { FOLLOW_UP_WORKING_DAYS } from '../lib/items'
import { composeUrl, useMailApp } from '../lib/mail'
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

/** What a draft or a suggestion is about, so the pane makes sense on its own. */
function About({ item }: { item: Item }) {
  return (
    <p className="text-[0.8125rem] text-ink-2">
      <span className="text-ink">{item.title}</span>
      {item.document && <span className="font-mono text-xs"> {item.document}</span>}
      {Number(item.amount) > 0 && <span className="font-mono text-xs"> {money(item.amount)}</span>}
    </p>
  )
}

/** The message as it came back, in the fields a person can change before sending. */
function Compose({ item, message, onAgain }: { item: Item; message: Draft; onAgain: () => void }) {
  const { viewer } = useViewer()
  const client = useQueryClient()
  const [mail] = useMailApp()
  const [to, setTo] = useState(message.recipient.email ?? '')
  const [subject, setSubject] = useState(message.subject)
  const [body, setBody] = useState(message.body)
  const [opened, setOpened] = useState(false)
  const [copied, setCopied] = useState(false)

  const logged = useMutation({
    mutationFn: () =>
      // Logging it also sets the date to come back if nothing has been heard.
      api.actOnItem(item.key, {
        action: 'update',
        actor: viewer.name,
        note: `Sent a message to ${message.recipient.name}: ${subject}`,
        follow_up_in_working_days: FOLLOW_UP_WORKING_DAYS,
      }),
    onSuccess: () => client.invalidateQueries({ predicate: (query) => query.queryKey[0] !== 'draft' }),
  })

  const ready = to.trim().includes('@') && subject.trim() !== '' && body.trim() !== ''

  function send() {
    // The message is handed to the person's own email, where they press send. This app cannot send mail.
    const url = composeUrl(mail.key, { to: to.trim(), subject, body })
    if (mail.key === 'default') window.location.href = url
    else window.open(url, '_blank', 'noopener')
    setOpened(true)
  }

  async function copy() {
    await navigator.clipboard.writeText(`To: ${to}\nSubject: ${subject}\n\n${body}`)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const field = 'min-w-0 flex-1 bg-transparent outline-none placeholder:text-muted'
  const tool =
    'grid size-8 place-items-center rounded-full text-muted transition-colors duration-150 ease-out hover:bg-raised hover:text-ink'

  return (
    <>
      {/* Laid out as a new message is in any mail app: a title bar, To, Subject, the text, and Send at the bottom left. */}
      <form
        onSubmit={(event) => {
          event.preventDefault()
          if (ready) send()
        }}
        className="flex flex-col overflow-hidden rounded-xl border border-hair bg-card shadow-float"
      >
        <p className="bg-raised px-4 py-2 text-[0.8125rem] font-medium">New message</p>
        <label className="flex items-center gap-3 border-b border-hair px-4 py-2 text-[0.8125rem]">
          <span className="text-muted">To</span>
          <input
            type="email"
            value={to}
            onChange={(event) => setTo(event.target.value)}
            placeholder="No address on file. Type one"
            className={field}
          />
        </label>
        <label className="flex items-center gap-3 border-b border-hair px-4 py-2 text-[0.8125rem]">
          <span className="text-muted">Subject</span>
          <input value={subject} onChange={(event) => setSubject(event.target.value)} className={`${field} font-medium`} />
        </label>
        <label>
          <span className="sr-only">Message</span>
          <textarea
            value={body}
            onChange={(event) => setBody(event.target.value)}
            rows={Math.min(18, Math.max(8, body.split('\n').length + Math.ceil(body.length / 48)))}
            className="block w-full resize-none bg-transparent px-4 py-3 leading-6 outline-none"
          />
        </label>
        <div className="flex items-center gap-1 px-3 pb-3">
          <button
            type="submit"
            disabled={!ready}
            className="mr-2 inline-flex h-9 items-center gap-2 rounded-full bg-btn px-5 text-[0.8125rem] font-medium text-btn-ink transition-[transform,opacity] duration-150 ease-out active:scale-[0.98] disabled:opacity-50"
          >
            Send
            <SendHorizontal {...ICON} />
          </button>
          <button type="button" title={copied ? 'Copied' : 'Copy message'} aria-label="Copy message" onClick={copy} className={tool}>
            {copied ? <Check {...ICON} /> : <Copy {...ICON} />}
          </button>
          <button type="button" title="Write it again" aria-label="Write it again" onClick={onAgain} className={tool}>
            <RotateCcw {...ICON} />
          </button>
        </div>
      </form>

      <dl className="grid grid-cols-[5rem_minmax(0,1fr)] gap-x-3 gap-y-1 text-[0.8125rem]">
        <dt className="text-ink-2">Written to</dt>
        <dd>{message.recipient.name}</dd>
        <dt className="text-ink-2">Why them</dt>
        <dd>{message.recipient.role}</dd>
        <dt className="text-ink-2">Sends with</dt>
        <dd className="flex flex-wrap items-center gap-x-2">
          {mail.logo && <img src={mail.logo} alt="" className="size-4 object-contain" />}
          {mail.name.charAt(0).toUpperCase() + mail.name.slice(1)}.{' '}
          <Link to="/connectors" className="text-ink-2 underline underline-offset-2 hover:text-ink">
            Change
          </Link>
        </dd>
      </dl>

      {message.warnings.length > 0 && (
        <div className="text-[0.8125rem]">
          <p className="font-medium text-accent-ink">Check before sending</p>
          <ul className="mt-1 flex list-disc flex-col gap-1 pl-5 text-ink-2">
            {message.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </div>
      )}

      {opened && (
        <div className="flex flex-col items-start gap-2 rounded-xl border border-hair bg-card p-4 text-[0.8125rem]">
          <p>
            The message is open in {mail.name}, ready to send. Once it has gone, log it. That records it and sets a follow-up in five working days
          </p>
          <Button disabled={logged.isPending || logged.isSuccess} onClick={() => logged.mutate()}>
            {logged.isSuccess ? 'Logged' : logged.isPending ? 'Logging' : 'Log that I sent it'}
          </Button>
          {logged.isError && <p className="text-neg">{logged.error.message}</p>}
        </div>
      )}

      <p className="text-xs leading-4 text-muted">
        Send opens this message in {mail.name} for you to send from your own address. Every figure in the draft was checked
        against the records as of the last sync
      </p>
    </>
  )
}

/** A drafted follow-up, shown as a message ready to send. The person sends it from their own email. */
function DraftPreview({ item }: { item: Item }) {
  const { viewer } = useViewer()

  const draft = useQuery({
    queryKey: ['draft', item.key, viewer.name],
    queryFn: () => api.draftForItem(item.key, viewer.name),
    // A draft is kept for the visit. A new one is written only when asked for.
    staleTime: Infinity,
    gcTime: Infinity,
  })

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-4">
      <div className="flex flex-col gap-4">
        <About item={item} />
        {draft.isFetching ? (
          <Working label="Writing a draft from the records" />
        ) : draft.isError ? (
          <ErrorNote error={draft.error} />
        ) : draft.data ? (
          // Keyed on when it was written, so a new draft replaces any edits to the old one.
          <Compose key={draft.dataUpdatedAt} item={item} message={draft.data} onAgain={() => draft.refetch()} />
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
function CodingSuggestion({ item }: { item: Item }) {
  const { viewer } = useViewer()
  const client = useQueryClient()
  const { close } = useAssistant()

  const suggestion = useQuery({
    queryKey: ['coding', item.key],
    queryFn: async () => {
      const result = await api.suggestJob(item.issue_ids[0])
      // The suggestion is written into the bill's history, so the lists need reading again.
      void client.invalidateQueries({ queryKey: ['items'] })
      return result
    },
    staleTime: Infinity,
    gcTime: Infinity,
  })

  const decide = useMutation({
    mutationFn: ({ accept, result }: { accept: boolean; result: Coding }) => {
      const what = result.decision === 'job' ? `job ${result.job_number} (${result.job_name})` : 'not a job cost'
      return api.actOnItem(item.key, {
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
        <About item={item} />
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
                ? 'The assistant would not guess. Use Log update once you know where the bill belongs'
                : 'Accepting records your decision and closes this. The bill itself is only changed in accounting'}
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
      {/* Keyed on the item so each one gets its own draft or suggestion. */}
      {view.kind === 'draft' && <DraftPreview key={view.item.key} item={view.item} />}
      {view.kind === 'coding' && <CodingSuggestion key={view.item.key} item={view.item} />}
    </aside>
  )
}
