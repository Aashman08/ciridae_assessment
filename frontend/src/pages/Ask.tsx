import { ChevronDown, FileText, HardHat, Receipt, TriangleAlert, X } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Composer, Messages } from '../components/Conversation'
import { Button } from '../components/ui'
import type { AskResponse, AskSource } from '../lib/api'
import { sourceLink, suggestionsFor } from '../lib/assistant'
import { useConversation } from '../lib/conversation'
import { useViewer } from '../lib/viewer'

const ICON = { size: '1rem', strokeWidth: 1.5, 'aria-hidden': true } as const

const SOURCES_OPEN = 'ask-sources-open'

const SOURCE_KINDS: Record<AskSource['kind'], { icon: LucideIcon; name: string }> = {
  job: { icon: HardHat, name: 'Job' },
  issue: { icon: TriangleAlert, name: 'Issue' },
  invoice: { icon: Receipt, name: 'Customer invoice' },
  vendor_bill: { icon: FileText, name: 'Vendor bill' },
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

/** The assistant on a page of its own, with the records its answers rest on beside it. */
export function Ask() {
  const { viewer } = useViewer()
  const conversation = useConversation()
  const [sourcesOpen, toggleSources] = useSourcesOpen()
  const { saved, failed, busy, count, clear } = conversation
  const sources = conversationSources(saved)

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

        <Messages
          conversation={conversation}
          suggestions={suggestionsFor({ kind: 'overview' }, Boolean(viewer.owner))}
          onSuggest={(question) => conversation.send(question)}
        />
        <Composer conversation={conversation} className="sticky bottom-0 z-20 mt-6 pt-2 pb-4" />
      </div>

      {sourcesOpen && <Sources sources={sources} onClose={toggleSources} className="sticky top-6 hidden xl:block" />}
    </div>
  )
}
