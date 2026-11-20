import { ChevronRight } from 'lucide-react'
import { Fragment, useState } from 'react'
import type { ReactNode } from 'react'
import type { Item } from '../lib/api'
import { dateTime, longDate, money, shortDate } from '../lib/format'
import { cx } from '../lib/styles'
import { Records } from './Records'
import { useItemWork } from './useItemWork'
import { Button, Empty } from './ui'

const ICON = { size: '1rem', strokeWidth: 1.5, 'aria-hidden': true } as const

const EVENTS: Record<string, string> = {
  opened: 'Found',
  commented: 'Note',
  assigned: 'Assigned',
  follow_up: 'Follow-up',
  suggested: 'Suggestion',
  resolved: 'Resolved',
  dismissed: 'Dismissed',
  reopened: 'Reopened',
  cleared: 'Cleared',
}

// Why the person named as owner has the item.
const OWNER_ROLES: Record<Item['owner_role'], string> = {
  ops_manager: "the job's ops manager",
  account_executive: "the job's account executive, as it has no ops manager",
  finance: 'finance, as the job has no ops manager or account executive',
  assigned: 'assigned by hand',
}

function Tag({ children, attention = false }: { children: ReactNode; attention?: boolean }) {
  return (
    <span
      className={cx(
        'inline-flex h-6 items-center rounded-md px-2 text-xs whitespace-nowrap ring-1 ring-hair ring-inset',
        attention ? 'bg-card text-accent-ink' : 'bg-raised text-ink-2',
      )}
    >
      {children}
    </span>
  )
}

/** An item's tags as a row of chips. A date it is waiting until is shown the same way. */
export function Tags({ tags, waitingUntil }: { tags: Item['tags']; waitingUntil?: string | null }) {
  return (
    <span className="flex flex-wrap gap-1">
      {tags.map((tag) => (
        <Tag key={tag.key} attention={tag.key === 'late' || tag.key === 'discount'}>
          {tag.label}
        </Tag>
      ))}
      {waitingUntil && <Tag>Waiting until {shortDate(waitingUntil)}</Tag>}
    </span>
  )
}

/** Everything about one item, opened in place under its row. */
function Detail({ item, work }: { item: Item; work: ReturnType<typeof useItemWork> }) {
  const { suggestion } = item
  const done = item.state === 'done'

  return (
    <div className="flex flex-col gap-5 px-5 py-5 whitespace-normal">
      <div className="grid grid-cols-1 gap-x-8 gap-y-5 @[58rem]:grid-cols-2">
        <div className="flex flex-col gap-1">
          <h4 className="text-[0.8125rem] text-ink-2">{done ? 'What was wrong' : 'What is wrong'}</h4>
          {item.details.map((detail) => (
            <p key={detail}>{detail}</p>
          ))}
        </div>
        <div className="flex flex-col gap-1">
          <h4 className="text-[0.8125rem] text-ink-2">{done ? 'How it was closed' : 'Suggested next step'}</h4>
          {done ? (
            <p>{item.resolution_note ?? 'A later sync no longer found this problem'}</p>
          ) : (
            <>
              <p className="font-medium">{suggestion.action.label}</p>
              <p className="text-ink-2">
                {suggestion.by === 'assistant' ? suggestion.reason : 'The standing rule for this kind of problem'}
              </p>
            </>
          )}
        </div>
      </div>

      <dl className="grid grid-cols-[repeat(auto-fit,minmax(11rem,1fr))] gap-x-6 gap-y-4">
        {[
          ['Owner', `${item.owner}, ${OWNER_ROLES[item.owner_role]}`],
          ...(item.company ? [[item.kind.startsWith('bill') ? 'Vendor' : 'Customer', item.company]] : []),
          ...(item.due_on ? [['Due', longDate(item.due_on)]] : []),
          ['Follow up on', item.follow_up_on ? longDate(item.follow_up_on) : 'No date set'],
        ].map(([label, value]) => (
          <div key={label} className="flex min-w-0 flex-col gap-1">
            <dt className="text-[0.8125rem] text-ink-2">{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>

      <div className="flex flex-col gap-2">
        <h4 className="text-[0.8125rem] text-ink-2">The records behind this</h4>
        <Records lines={item.evidence} />
      </div>

      {item.source_notes.length > 0 && (
        <div className="flex flex-col gap-2">
          <h4 className="text-[0.8125rem] text-ink-2">Notes in accounting</h4>
          <ul className="flex flex-col gap-3">
            {item.source_notes.map((note) => (
              <li key={note.on + note.note} className="text-[0.8125rem]">
                <p>
                  <span className="font-medium">{note.by}</span>
                  <span className="pl-2 font-mono text-xs text-muted">{longDate(note.on)}</span>
                </p>
                <p className="text-ink-2">{note.note}</p>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex flex-col gap-2">
        <h4 className="text-[0.8125rem] text-ink-2">History</h4>
        <ol className="flex flex-col gap-3">
          {item.events.map((event) => (
            <li key={event.id} className="text-[0.8125rem]">
              <p>
                <span className="font-medium">{EVENTS[event.kind] ?? event.kind}</span>
                <span className="text-ink-2">
                  {' '}
                  by {event.actor === 'system' ? 'a sync' : event.actor === 'assistant' ? 'the assistant' : event.actor}
                </span>
                <span className="pl-2 font-mono text-xs text-muted">{dateTime(event.created_at)}</span>
              </p>
              {event.note && <p className="text-ink-2">{event.note}</p>}
            </li>
          ))}
        </ol>
      </div>

      {!done && (
        <div className="flex flex-wrap gap-2">
          {/* The work the rules name is always on offer, whatever the assistant suggested. */}
          {suggestion.action.key !== item.action.key && (
            <Button onClick={() => work.start(item, { ...suggestion, action: item.action })}>{item.action.label}</Button>
          )}
          <Button onClick={() => work.update(item)}>Log update</Button>
          {suggestion.action.key !== 'dismiss' && <Button onClick={() => work.dismiss(item)}>Dismiss as expected</Button>}
        </div>
      )}
    </div>
  )
}

interface ItemTableProps {
  items: Item[]
  /** Shown on a list that spans jobs. Left out under a job, where every row would repeat it. */
  showJob?: boolean
  empty?: string
}

/**
 * What needs fixing, one row each: what it is, which document, its tags, how
 * much, and a button that starts the next step. Clicking a row opens the rest
 * in place: what is wrong, the records behind it, and its history.
 */
export function ItemTable({ items, showJob = false, empty = 'Nothing needs fixing here' }: ItemTableProps) {
  const work = useItemWork()
  const [open, setOpen] = useState<string | null>(null)
  if (items.length === 0) return <Empty>{empty}</Empty>
  const columns = showJob ? 7 : 6

  return (
    <>
      <div className="relative overflow-x-auto">
        <table className="data-table dense">
          <thead>
            <tr>
              <th className="w-10">
                <span className="sr-only">Open</span>
              </th>
              <th>What</th>
              <th className="max-md:hidden">Document</th>
              {showJob && <th className="max-md:hidden">Job ID</th>}
              <th className="max-md:hidden">Tags</th>
              <th className="num">Amount</th>
              <th className="text-right!">Next step</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => {
              const expanded = open === item.key
              const done = item.state === 'done'
              return (
                <Fragment key={item.key}>
                  <tr className="clickable" aria-expanded={expanded} onClick={() => setOpen(expanded ? null : item.key)}>
                    <td className="pr-0!">
                      <ChevronRight
                        {...ICON}
                        className={cx('text-muted transition-transform duration-150 ease-out', expanded && 'rotate-90')}
                      />
                    </td>
                    <td>
                      {/* The button keeps the row reachable by keyboard; the row click covers everywhere else. */}
                      <button
                        type="button"
                        className="text-left font-medium"
                        onClick={(event) => {
                          event.stopPropagation()
                          setOpen(expanded ? null : item.key)
                        }}
                      >
                        {item.title}
                      </button>
                    </td>
                    <td className="font-mono text-[0.8125rem] text-ink-2 max-md:hidden">{item.document ?? ''}</td>
                    {showJob && <td className="font-mono text-[0.8125rem] text-ink-2 max-md:hidden">{item.job_number ?? ''}</td>}
                    {/* Wide enough for two tags side by side, so four wrap to two lines and not four. */}
                    <td className="min-w-[12rem] max-md:hidden">
                      <Tags tags={item.tags} waitingUntil={item.state === 'waiting' ? item.follow_up_on : null} />
                    </td>
                    <td className="num">{Number(item.amount) > 0 ? money(item.amount) : ''}</td>
                    <td className="text-right">
                      <Button
                        disabled={work.busy}
                        title={item.suggestion.reason ?? undefined}
                        onClick={(event) => {
                          // The button starts the work; it must not also open the row.
                          event.stopPropagation()
                          if (done) work.reopen(item)
                          else work.start(item)
                        }}
                      >
                        {done ? 'Reopen' : item.suggestion.action.label}
                      </Button>
                    </td>
                  </tr>
                  {expanded && (
                    <tr>
                      <td colSpan={columns} className="h-auto! bg-bg p-0!">
                        <Detail item={item} work={work} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
      {work.dialogs}
    </>
  )
}
