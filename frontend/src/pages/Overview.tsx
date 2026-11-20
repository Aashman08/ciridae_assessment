import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ItemTable } from '../components/ItemTable'
import { JobTable } from '../components/JobTable'
import { Card, CardHead, Loaded, PageHead, Stat } from '../components/ui'
import { api } from '../lib/api'
import type { Summary } from '../lib/api'
import { longDate, money, monthAndYear, percent, plural } from '../lib/format'
import { buttonClass } from '../lib/styles'
import { useViewer } from '../lib/viewer'

// The page is one column. Every block below the figures runs the full width,
// so everything shares the same left and right edge and nothing sits off to the side.
const STATS = 'grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4'

function PastDue({ amount }: { amount: string }) {
  return (
    <>
      <span className="text-accent-ink">{money(amount)}</span> past due
    </>
  )
}

/** Where the systems disagree, largest first, as a table like every other list in the app. */
function IssuesByType({ summary }: { summary: Summary }) {
  const navigate = useNavigate()
  const largest = Math.max(...summary.issues_by_type.map((t) => Number(t.amount)), 1)

  return (
    <Card>
      <CardHead title="What each check found">
        <Link to="/issues" className={buttonClass()}>
          All issues
        </Link>
      </CardHead>
      <p className="px-5 pb-3 text-[0.8125rem] text-ink-2">
        {summary.flagged_documents.count} invoices and bills are flagged, with{' '}
        <span className="font-mono text-xs text-ink">{money(summary.flagged_documents.amount)}</span> unpaid on them. One
        document can sit under several types, so the amounts below overlap and do not add up
      </p>
      <div className="overflow-x-auto">
        <table className="data-table">
          <thead>
            <tr>
              <th>Type</th>
              <th>Severity</th>
              <th className="num">Findings</th>
              <th className="num">Amount</th>
              <th className="w-2/5 max-md:hidden">
                <span className="sr-only">Share of the largest</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {summary.issues_by_type.map((type) => (
              <tr key={type.type_key} className="clickable" onClick={() => navigate(`/issues?type=${type.type_key}`)}>
                <td>
                  <Link to={`/issues?type=${type.type_key}`} onClick={(e) => e.stopPropagation()}>
                    {type.title}
                  </Link>
                </td>
                <td className={`capitalize ${type.severity === 'high' ? '' : 'text-ink-2'}`}>{type.severity}</td>
                <td className="num">{type.count}</td>
                <td className="num">{Number(type.amount) > 0 ? money(type.amount) : ''}</td>
                <td className="max-md:hidden">
                  <span className="block h-1 rounded-sm bg-raised">
                    <span className="block h-1 rounded-sm bg-ink-2" style={{ width: `${(Number(type.amount) / largest) * 100}%` }} />
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

type Stage = Summary['contract_to_cash']['stages'][number]

// Each part of the contract value: what to call it, how dark to draw it, and where its detail is.
// One hue from dark to light follows the money from in the bank to not yet earned.
const STAGES: Record<Stage['key'], { label: string; ink: number; to?: string }> = {
  collected: { label: 'Collected', ink: 88 },
  sent_not_collected: { label: 'Sent, not collected', ink: 62, to: '/invoices?balance=open' },
  invoiced_not_sent: { label: 'Invoiced, not sent', ink: 42, to: '/issues?type=not_sent' },
  earned_not_invoiced: { label: 'Earned, not invoiced', ink: 26 },
  not_yet_earned: { label: 'Not yet earned', ink: 12 },
}

function shade(key: Stage['key']): string {
  return `color-mix(in oklab, var(--ink) ${STAGES[key].ink}%, var(--card))`
}

/**
 * The contract value as one bar, split by how far each dollar has got on its
 * way to the bank. The widths show where the money is sitting; the table under
 * it gives each part's figure.
 */
function ContractFlow({ flow }: { flow: Summary['contract_to_cash'] }) {
  const navigate = useNavigate()
  const [active, setActive] = useState<Stage['key'] | null>(null)

  return (
    <Card>
      <CardHead title="From contract to cash, all jobs">
        <p className="text-[0.8125rem] text-ink-2">
          Contract value <span className="pl-2 font-mono text-ink tabular-nums">{money(flow.contract_value)}</span>
        </p>
      </CardHead>

      <div className="px-5 pb-4">
        <div role="img" aria-label="Contract value by how far it has got" className="flex h-10 gap-0.5 overflow-hidden rounded-lg">
          {flow.stages
            .filter((stage) => Number(stage.amount) > 0)
            .map((stage) => (
              <span
                key={stage.key}
                title={`${STAGES[stage.key].label}: ${money(stage.amount)}, ${percent(stage.share_pct)}`}
                onMouseEnter={() => setActive(stage.key)}
                onMouseLeave={() => setActive(null)}
                className="min-w-1 transition-opacity duration-150 ease-out"
                style={{
                  flexGrow: Number(stage.amount),
                  flexBasis: 0,
                  background: shade(stage.key),
                  opacity: active && active !== stage.key ? 0.35 : 1,
                }}
              />
            ))}
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="data-table">
          <thead>
            <tr>
              <th>Where it is</th>
              <th className="num">Amount</th>
              <th className="num">Share of contract</th>
            </tr>
          </thead>
          <tbody>
            {flow.stages.map((stage) => {
              const { label, to } = STAGES[stage.key]
              return (
                <tr
                  key={stage.key}
                  className={to ? 'clickable' : undefined}
                  onClick={to ? () => navigate(to) : undefined}
                  onMouseEnter={() => setActive(stage.key)}
                  onMouseLeave={() => setActive(null)}
                >
                  <td>
                    <span className="flex items-center gap-3">
                      <span aria-hidden className="size-3 shrink-0 rounded-sm ring-1 ring-hair ring-inset" style={{ background: shade(stage.key) }} />
                      {to ? (
                        <Link to={to} onClick={(event) => event.stopPropagation()}>
                          {label}
                        </Link>
                      ) : (
                        label
                      )}
                    </span>
                  </td>
                  <td className="num">{money(stage.amount)}</td>
                  <td className="num text-ink-2">{percent(stage.share_pct)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

/** Finance's view: the whole company's cash position and where the systems disagree. */
function CompanyOverview({ summary }: { summary: Summary }) {
  const { cash, contract_to_cash: flow } = summary
  const first = useQuery({ queryKey: ['jobs', 'first-six'], queryFn: () => api.jobs({ limit: 6 }) })

  return (
    <>
      <PageHead title={monthAndYear(summary.as_of)} sub={`${plural(summary.job_count, 'job')}, as of ${longDate(summary.as_of)}`} />

      <div className={STATS}>
        <Stat label="Owed by customers" value={money(cash.owed)} note={<PastDue amount={cash.past_due} />} />
        <Stat label="Invoices not sent" value={money(cash.invoices_not_sent)} note={plural(cash.invoices_not_sent_count, 'invoice')} />
        <Stat
          label="Vendor bills unpaid"
          value={money(cash.vendor_bills_unpaid)}
          note={`${plural(cash.vendor_bills_count, 'bill')}, none in the ledger`}
        />
        <Stat
          label="To fix"
          value={summary.open_item_count}
          note={`on ${summary.jobs_with_issues} of ${plural(summary.job_count, 'job')}`}
        />
      </div>

      <ContractFlow flow={flow} />

      <IssuesByType summary={summary} />

      <Card>
        <CardHead title="Jobs to look at first">
          <Link to="/jobs" className={buttonClass()}>
            All jobs
          </Link>
        </CardHead>
        <Loaded query={first}>{(page) => <JobTable jobs={page.data} />}</Loaded>
      </Card>
    </>
  )
}

/** An ops manager's view: what is stuck on their own jobs, largest first. */
function MyOverview({ summary, owner }: { summary: Summary; owner: string }) {
  const { cash } = summary
  // Everything open on this person's jobs as one list: what needs action first, then the largest.
  const todo = useQuery({
    queryKey: ['items', 'open', owner, ''],
    queryFn: () => api.items({ state: 'open', owner }),
    select: (found) =>
      found.groups
        .flatMap((group) => group.items)
        .sort((a, b) => Number(a.state !== 'needs_action') - Number(b.state !== 'needs_action') || Number(b.amount) - Number(a.amount)),
  })
  const jobs = useQuery({ queryKey: ['jobs', owner, 'mine'], queryFn: () => api.jobs({ owner, limit: 100 }) })

  return (
    <>
      <PageHead title="My jobs" aside={summary.job_count} sub={`As of ${longDate(summary.as_of)}`} />

      <div className={STATS}>
        <Stat label="Owed by customers" value={money(cash.owed)} note={<PastDue amount={cash.past_due} />} />
        <Stat label="Invoices not sent" value={money(cash.invoices_not_sent)} note={plural(cash.invoices_not_sent_count, 'invoice')} />
        <Stat
          label="Vendor bills unpaid"
          value={money(cash.vendor_bills_unpaid)}
          note={`${plural(cash.vendor_bills_count, 'bill')} on my jobs`}
        />
        <Stat label="Needs me" value={summary.open_item_count} note={`across ${plural(summary.jobs_with_issues, 'job')}`} />
      </div>

      <Card>
        <CardHead title="To do, largest first" />
        <Loaded query={todo}>{(items) => <ItemTable items={items} showJob empty="Nothing on your jobs needs fixing" />}</Loaded>
      </Card>

      <Card>
        <CardHead title="My jobs">
          <Link to="/jobs" className={buttonClass()}>
            Compare figures
          </Link>
        </CardHead>
        <Loaded query={jobs}>{(page) => <JobTable jobs={page.data} showOwner={false} />}</Loaded>
      </Card>
    </>
  )
}

export function Overview() {
  const { viewer } = useViewer()
  const summary = useQuery({ queryKey: ['summary', viewer.owner], queryFn: () => api.summary(viewer.owner) })

  return (
    <Loaded query={summary}>
      {(data) => (viewer.owner ? <MyOverview summary={data} owner={viewer.owner} /> : <CompanyOverview summary={data} />)}
    </Loaded>
  )
}
