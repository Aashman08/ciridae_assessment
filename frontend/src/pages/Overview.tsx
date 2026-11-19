import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { IssueTable } from '../components/IssueTable'
import { JobTable } from '../components/JobTable'
import { BarRow, Card, CardHead, Loaded, PageHead, Stat } from '../components/ui'
import { api } from '../lib/api'
import type { Summary } from '../lib/api'
import { longDate, money, monthAndYear, plural } from '../lib/format'
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
      <CardHead title="Issues by type">
        <Link to="/issues" className={buttonClass()}>
          All issues
        </Link>
      </CardHead>
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
                <td className="text-ink-2 capitalize">{type.severity}</td>
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

/** Finance's view: the whole company's cash position and where the systems disagree. */
function CompanyOverview({ summary }: { summary: Summary }) {
  const { cash, contract_to_cash: flow } = summary
  const first = useQuery({ queryKey: ['jobs', 'first-six'], queryFn: () => api.jobs({ limit: 6 }) })
  const contract = Number(flow.contract_value)

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
          label="Open issues"
          value={summary.open_issue_count}
          note={`on ${summary.jobs_with_issues} of ${plural(summary.job_count, 'job')}`}
        />
      </div>

      <Card>
        <CardHead title="From contract to cash, all jobs" />
        <div className="flex flex-col gap-2 px-5 pb-4">
          <BarRow label="Contract value" amount={contract} max={contract} tone="outline" />
          <BarRow label="Earned, per ledger" amount={Number(flow.earned)} max={contract} />
          <BarRow label="Invoiced" amount={Number(flow.invoiced)} max={contract} />
          <BarRow label="Sent to customers" amount={Number(flow.sent)} max={contract} />
          <BarRow label="Collected" amount={Number(flow.collected)} max={contract} />
        </div>
        <p className="px-5 pb-5 text-xs leading-4 text-muted">
          {money(Number(flow.invoiced) - Number(flow.sent))} is invoiced but not sent.{' '}
          {money(Number(flow.sent) - Number(flow.collected))} is sent but not collected
        </p>
      </Card>

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
  const todo = useQuery({ queryKey: ['issues', owner, 'todo'], queryFn: () => api.issues({ owner, limit: 100 }) })
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
        <Stat label="Needs me" value={summary.open_issue_count} note={`across ${plural(summary.jobs_with_issues, 'job')}`} />
      </div>

      <Card>
        <CardHead title="To do, largest first" />
        <Loaded query={todo}>{(page) => <IssueTable issues={page.data} showOwner={false} />}</Loaded>
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
