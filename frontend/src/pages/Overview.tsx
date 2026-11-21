import { useQuery } from '@tanstack/react-query'
import { CalendarClock, ClipboardList, FileText, Gauge, Receipt, Send, Siren, TrendingUp, UserX } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Chart } from '../components/Chart'
import { Donut } from '../components/Donut'
import { ItemTable, Tags } from '../components/ItemTable'
import { JobTable } from '../components/JobTable'
import { Card, CardHead, Loaded, PageHead, Select, Stat } from '../components/ui'
import { api } from '../lib/api'
import type { Finance, FinancePeriod, Operations, Summary } from '../lib/api'
import { longDate, money, percent, plural, shortDate, words } from '../lib/format'
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

type Stage = Summary['contract_to_cash']['stages'][number]

// Each part of the contract value: what to call it, its colour, and where its detail is.
// Every stage has its own hue from the chart colours: green for money in the bank, amber for work not yet billed. Work not
// yet earned is not money moving at all, so it is grey.
const STAGES: Record<Stage['key'], { label: string; colour: string; to?: string }> = {
  collected: { label: 'Collected', colour: 'var(--series-2)' },
  sent_not_collected: { label: 'Sent, not collected', colour: 'var(--series-1)', to: '/invoices?balance=open' },
  invoiced_not_sent: { label: 'Invoiced, not sent', colour: 'var(--series-3)', to: '/issues?type=not_sent' },
  earned_not_invoiced: { label: 'Earned, not invoiced', colour: 'var(--series-4)' },
  not_yet_earned: { label: 'Not yet earned', colour: 'var(--tint-slate)' },
}

function shade(key: Stage['key']): string {
  return STAGES[key].colour
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

const AGES: Record<Finance['receivables_by_age'][number]['bucket'], string> = {
  not_due: 'Not yet due',
  late_1_30: '1 to 30 days',
  late_31_60: '31 to 60 days',
  late_over_60: 'Over 60 days',
}

// Cost codes short enough to sit under a bar. Any other code is shown as it is written.
const COST_CODES: Record<string, string> = {
  INTERNAL_LABOR: 'Own labor',
  EXTERNAL_LABOR: 'Hired labor',
  SPECIALTY_SUBCONTRACTOR: 'Subcontractors',
  MATERIALS_AND_SUPPLIES: 'Materials',
  EQUIPMENT_RENTAL_AND_FUEL: 'Equipment',
}

/** "2026-07" as "Jul 2026". */
function monthName(month: string): string {
  return new Date(`${month}-01T00:00:00Z`).toLocaleDateString('en-GB', { month: 'short', year: 'numeric', timeZone: 'UTC' })
}

// The four ledger figures, drawn together, in this order so each keeps its colour.
// Profit is not here: it is the backend's figure, and is in the table further down.
const TRENDS = [
  { key: 'revenue', label: 'Revenue, per ledger' },
  { key: 'collected', label: 'Cash collected' },
  { key: 'invoiced', label: 'Invoiced' },
  { key: 'cost', label: 'Cost, per ledger' },
] as const

/**
 * Revenue, cash, invoicing and cost over time on one chart, a week or a month
 * at a time, either as what happened in each period or as running totals.
 * Both choices are kept in the address, like a filter.
 */
function LedgerTrend({ ledger }: { ledger: Finance }) {
  const [params, setParams] = useSearchParams()
  const monthly = params.get('by') === 'month'
  const running = params.get('total') === 'running'
  const set = (key: string, value: string, fallback: string) =>
    setParams(
      (now) => {
        const next = new URLSearchParams(now)
        if (value === fallback) next.delete(key)
        else next.set(key, value)
        return next
      },
      { replace: true },
    )

  const periods: FinancePeriod[] = monthly ? ledger.by_month : ledger.by_week
  const labels = monthly ? ledger.by_month.map((m) => monthName(m.month)) : ledger.by_week.map((w) => shortDate(w.week_of))
  const period = monthly ? 'month' : 'week'

  return (
    <Chart
      kind="area"
      title={running ? `Revenue, cash and cost, running total by ${period}` : `Revenue, cash and cost, by ${period}`}
      unit="money"
      points={labels}
      series={TRENDS.map(({ key, label }) => ({
        label,
        values: periods.map((p) => Number(running ? p[`${key}_to_date`] : p[key])),
      }))}
      aside={
        <div className="flex flex-wrap items-center gap-2">
          <Select
            label="Show"
            value={running ? 'running' : 'each'}
            onChange={(value) => set('total', value, 'each')}
            options={[
              { value: 'each', label: monthly ? 'Monthly total' : 'Weekly total' },
              { value: 'running', label: 'Running total' },
            ]}
            className="w-40"
          />
          <Select
            label="By"
            value={period}
            onChange={(value) => set('by', value, 'week')}
            options={[
              { value: 'week', label: 'Week' },
              { value: 'month', label: 'Month' },
            ]}
            className="w-28"
          />
        </div>
      }
      note={
        running
          ? `Each line adds up from the first ${period}. The gap between revenue and invoiced is work earned and not yet billed, or billed ahead of being earned; the gap between invoiced and cash is what customers still owe. Figures run to ${longDate(ledger.as_of)}`
          : `Four separate measures, each dated when it happened: revenue and cost when the ledger booked them, invoices by their date, cash when it arrived. They do not add up to each other. Figures run to ${longDate(ledger.as_of)}`
      }
    />
  )
}

/**
 * Finance's view: the ledger. What was earned and spent and when, where the
 * cost went, how the contract value is turning into cash, and what is owed.
 * Problems on individual jobs are on the Issues tab, not here.
 */
function FinanceOverview({ summary }: { summary: Summary }) {
  const { cash, contract_to_cash: flow } = summary
  const finance = useQuery({ queryKey: ['finance'], queryFn: api.finance })
  const thin = useQuery({
    queryKey: ['jobs', 'lowest-margin'],
    queryFn: () => api.jobs({ sort: 'margin', order: 'asc', limit: 6 }),
  })

  return (
    <>
      <PageHead title="Finance" sub={`${plural(summary.job_count, 'job')}, figures as of ${longDate(summary.as_of)}`} />

      <Loaded query={finance}>
        {(ledger) => (
          <>
            <div className={STATS}>
              <Stat
                label="Profit, per ledger"
                icon={TrendingUp}
                value={money(ledger.profit)}
                note={`${percent(ledger.margin_pct)} of ${money(ledger.revenue)} revenue`}
              />
              <Stat label="Owed by customers" icon={Receipt} value={money(cash.owed)} note={<PastDue amount={cash.past_due} />} />
              <Stat
                label="Invoices not sent"
                icon={Send}
                value={money(cash.invoices_not_sent)}
                note={plural(cash.invoices_not_sent_count, 'invoice')}
              />
              <Stat
                label="Vendor bills unpaid"
                icon={FileText}
                value={money(cash.vendor_bills_unpaid)}
                note={`${plural(cash.vendor_bills_count, 'bill')}, none in the ledger`}
              />
            </div>

            <LedgerTrend ledger={ledger} />

            <div className="grid grid-cols-1 gap-4 @[54rem]:grid-cols-2">
              <Donut
                title="Cost by cost code"
                heading="Cost code"
                slices={ledger.cost_by_code.map((c) => ({
                  label: COST_CODES[c.cost_code] ?? words(c.cost_code),
                  amount: c.ops_cost,
                  share_pct: c.share_pct,
                }))}
                total={{ label: 'Logged', amount: ledger.logged_cost }}
                note={
                  ledger.ledger_cost_accounts.length === 1
                    ? `This is the project teams' cost log. The ledger posts all job cost to one account, ${ledger.ledger_cost_accounts[0]}, so it cannot be split by cost code`
                    : "This is the project teams' cost log"
                }
              />
              <Chart
                kind="bar"
                title="What customers owe, by days late"
                unit="money"
                points={ledger.receivables_by_age.map((a) => AGES[a.bucket])}
                series={[{ label: 'Unpaid on sent invoices', values: ledger.receivables_by_age.map((a) => Number(a.amount)) }]}
                note="Invoices that have been sent and not fully paid. Invoices not yet sent are not in this"
              />
            </div>

            <ContractFlow flow={flow} />

            <Card>
              <CardHead title="Profit by kind of work, per ledger" />
              <div className="overflow-x-auto">
                <table className="data-table dense">
                  <thead>
                    <tr>
                      <th>Kind of work</th>
                      <th className="num">Jobs</th>
                      <th className="num">Revenue</th>
                      <th className="num">Cost</th>
                      <th className="num">Profit</th>
                      <th className="num">Margin</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ledger.by_service_line.map((kind) => (
                      <tr key={kind.service_line}>
                        <td>{words(kind.service_line)}</td>
                        <td className="num">{kind.jobs}</td>
                        <td className="num">{money(kind.revenue)}</td>
                        <td className="num">{money(kind.cost)}</td>
                        <td className={`num ${Number(kind.profit) < 0 ? 'text-neg' : ''}`}>{money(kind.profit)}</td>
                        <td className="num">{percent(kind.margin_pct)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </>
        )}
      </Loaded>

      <Card>
        <CardHead title="Lowest margin first">
          <Link to="/jobs?sort=margin&order=asc" className={buttonClass()}>
            All jobs
          </Link>
        </CardHead>
        <Loaded query={thin}>{(page) => <JobTable jobs={page.data} full />}</Loaded>
      </Card>
    </>
  )
}

const PACE_FLAGS: Record<Operations['in_progress'][number]['flags'][number], string> = {
  past_finish: 'Past finish',
  no_activity: 'No work logged',
  budget_burn: 'Spending ahead',
}

/** A short date, or a dash when there is none. */
function day(value: string | null): string {
  return value ? shortDate(value) : ''
}

/**
 * Operations' view across every job, one block for each thing Luis has to know:
 * whether urgent jobs started quickly, which won jobs are still waiting to start,
 * how each job in progress is pacing against its time and budget, and who owns what.
 */
function OperationsOverview({ summary }: { summary: Summary }) {
  const navigate = useNavigate()
  const ops = useQuery({ queryKey: ['operations'], queryFn: api.operations })

  return (
    <>
      <PageHead title="Operations" sub={`${plural(summary.job_count, 'job')}, as of ${longDate(summary.as_of)}`} />

      <Loaded query={ops}>
        {(data) => {
          const onTime = data.urgent.filter((job) => job.started_in_time).length
          const fromDamage = data.urgent
            .map((job) => job.days_damage_to_site)
            .filter((days): days is number => days !== null)
            .sort((a, b) => a - b)
          const median = fromDamage.length ? fromDamage[Math.floor((fromDamage.length - 1) / 2)] : null
          const slow = data.waiting.filter((job) => job.slow).length
          const stalled = data.in_progress.filter((job) => job.flags.includes('past_finish') || job.flags.includes('no_activity')).length
          const ahead = data.in_progress.filter((job) => job.flags.includes('budget_burn')).length
          const offPace = data.in_progress.filter((job) => job.flags.length > 0).length
          const unowned = data.owners.find((owner) => owner.name === 'None assigned')
          const unownedJobs = unowned ? unowned.jobs_in_progress + unowned.jobs_not_started : 0

          return (
            <>
              <div className={STATS}>
                <Stat
                  label="Urgent jobs, damage to on site"
                  icon={Siren}
                  value={median === null ? 'No dates' : `${median} ${median === 1 ? 'day' : 'days'}`}
                  note={`Median. ${onTime} of ${data.urgent.length} on site the day they were won`}
                />
                <Stat
                  label="Won, not yet on site"
                  icon={CalendarClock}
                  value={data.waiting.length}
                  note={slow ? `${plural(slow, 'job')} slower than ${data.start_tolerance_days} days` : 'All within tolerance'}
                />
                <Stat
                  label="In progress, off pace"
                  icon={Gauge}
                  value={`${offPace} of ${data.in_progress.length}`}
                  note={`${stalled} stalled, ${ahead} spending ahead of schedule`}
                />
                <Stat
                  label="Active jobs with no ops manager"
                  icon={UserX}
                  value={unownedJobs}
                  note={`of ${plural(data.in_progress.length + data.waiting.length, 'active job')}`}
                />
              </div>

              <Card>
                <CardHead title="Jobs in progress, against their time and budget" />
                <p className="px-5 pb-3 text-[0.8125rem] text-ink-2">
                  A job that has used more of its budget than of its time will run out of money before it finishes. This
                  shows it while there is still time to act
                </p>
                <div className="overflow-x-auto">
                  <table className="data-table dense">
                    <thead>
                      <tr>
                        <th>Job ID</th>
                        <th>Job</th>
                        <th className="max-xl:hidden">Ops manager</th>
                        <th>Finish</th>
                        <th className="num">Time gone</th>
                        <th className="num">Budget used</th>
                        <th className="max-lg:hidden">Last work</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.in_progress.map((job) => {
                        const ahead = job.budget_used_pct !== null && job.time_gone_pct !== null
                          && Number(job.budget_used_pct) > Number(job.time_gone_pct)
                        return (
                          <tr key={job.job_number} className="clickable" onClick={() => navigate(`/jobs/${job.job_number}`)}>
                            <td className="font-mono text-[0.8125rem] text-ink-2">{job.job_number}</td>
                            <td>
                              <Link
                                to={`/jobs/${job.job_number}`}
                                className="block max-w-[18rem] truncate"
                                title={job.name}
                                onClick={(event) => event.stopPropagation()}
                              >
                                {job.name}
                              </Link>
                            </td>
                            <td className={`max-xl:hidden ${job.ops_manager ? 'text-ink-2' : 'text-accent-ink'}`}>
                              {job.ops_manager ?? 'None assigned'}
                            </td>
                            <td className={job.flags.includes('past_finish') ? 'text-accent-ink' : 'text-ink-2'}>
                              {day(job.planned_finish_on)}
                            </td>
                            <td className="num text-ink-2">{percent(job.time_gone_pct)}</td>
                            <td className={`num ${ahead && job.flags.includes('budget_burn') ? 'text-accent-ink' : ''}`}>
                              {percent(job.budget_used_pct)}
                            </td>
                            <td className={`max-lg:hidden ${job.flags.includes('no_activity') ? 'text-accent-ink' : 'text-ink-2'}`}>
                              {day(job.last_work_on)}
                            </td>
                            <td>
                              {job.flags.length ? (
                                <Tags tags={job.flags.map((flag) => ({ key: flag, label: PACE_FLAGS[flag] }))} />
                              ) : (
                                <span className="text-ink-2">On track</span>
                              )}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </Card>

              <Card>
                <CardHead title="Won, not yet on site" />
                <p className="px-5 pb-3 text-[0.8125rem] text-ink-2">
                  Planned work should be on site within {data.start_tolerance_days} days of the win, urgent work within a day
                </p>
                <div className="overflow-x-auto">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Job ID</th>
                        <th>Job</th>
                        <th>Ops manager</th>
                        <th>Won</th>
                        <th>Planned start</th>
                        <th className="num">Days from win to start</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.waiting.map((job) => (
                        <tr key={job.job_number} className="clickable" onClick={() => navigate(`/jobs/${job.job_number}`)}>
                          <td className="font-mono text-[0.8125rem] text-ink-2">{job.job_number}</td>
                          <td>
                            <Link to={`/jobs/${job.job_number}`} onClick={(event) => event.stopPropagation()}>
                              {job.name}
                            </Link>
                          </td>
                          <td className={job.ops_manager ? 'text-ink-2' : 'text-accent-ink'}>{job.ops_manager ?? 'None assigned'}</td>
                          <td className="text-ink-2">{day(job.won_on)}</td>
                          <td className="text-ink-2">{job.on_site_on ? shortDate(job.on_site_on) : 'Not set'}</td>
                          <td className={`num ${job.slow ? 'text-accent-ink' : ''}`}>{job.days_win_to_start ?? ''}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>

              <Card>
                <CardHead title="Urgent jobs, from damage to on site" />
                <p className="px-5 pb-3 text-[0.8125rem] text-ink-2">Urgent means {data.urgent_rule.charAt(0).toLowerCase() + data.urgent_rule.slice(1)}</p>
                <div className="overflow-x-auto">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Job ID</th>
                        <th>Job</th>
                        <th className="max-2xl:hidden">Why urgent</th>
                        <th>Damage</th>
                        <th>Won</th>
                        <th>On site</th>
                        <th className="num">Days from damage to site</th>
                        <th className="num">Days from win to site</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.urgent.map((job) => (
                        <tr key={job.job_number} className="clickable" onClick={() => navigate(`/jobs/${job.job_number}`)}>
                          <td className="font-mono text-[0.8125rem] text-ink-2">{job.job_number}</td>
                          <td>
                            <Link
                              to={`/jobs/${job.job_number}`}
                              className="block max-w-[18rem] truncate"
                              title={job.name}
                              onClick={(event) => event.stopPropagation()}
                            >
                              {job.name}
                            </Link>
                          </td>
                          <td className="text-ink-2 max-2xl:hidden">{job.urgent_reason}</td>
                          <td className="text-ink-2">{day(job.incident_on)}</td>
                          <td className="text-ink-2">{day(job.won_on)}</td>
                          <td className="text-ink-2">{day(job.on_site_on)}</td>
                          <td className="num">{job.days_damage_to_site ?? ''}</td>
                          <td className={`num ${job.started_in_time ? '' : 'text-accent-ink'}`}>{job.days_win_to_site ?? ''}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>

              <Card>
                <CardHead title="Who owns what">
                  <Link to="/issues" className={buttonClass()}>
                    All issues
                  </Link>
                </CardHead>
                <div className="overflow-x-auto">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Ops manager</th>
                        <th className="num">In progress</th>
                        <th className="num">Not started</th>
                        <th className="num">To fix</th>
                        <th className="num">Need action</th>
                        <th className="num">About schedule</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.owners.map((owner) => {
                        const nobody = owner.name === 'None assigned'
                        const to = nobody ? '/issues?type=no_owner' : `/issues?owner=${encodeURIComponent(owner.name)}`
                        return (
                          <tr key={owner.name} className="clickable" onClick={() => navigate(to)}>
                            <td className={nobody ? 'text-accent-ink' : ''}>
                              <Link to={to} onClick={(event) => event.stopPropagation()}>
                                {owner.name}
                              </Link>
                            </td>
                            <td className="num">{owner.jobs_in_progress}</td>
                            <td className="num">{owner.jobs_not_started}</td>
                            <td className="num">{owner.open_items}</td>
                            <td className="num">{owner.needing_action}</td>
                            <td className="num">{owner.schedule_items}</td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </Card>
            </>
          )
        }}
      </Loaded>

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
        <Stat label="Owed by customers" icon={Receipt} value={money(cash.owed)} note={<PastDue amount={cash.past_due} />} />
        <Stat
          label="Invoices not sent"
          icon={Send}
          value={money(cash.invoices_not_sent)}
          note={plural(cash.invoices_not_sent_count, 'invoice')}
        />
        <Stat
          icon={FileText}
          label="Vendor bills unpaid"
          value={money(cash.vendor_bills_unpaid)}
          note={`${plural(cash.vendor_bills_count, 'bill')} on my jobs`}
        />
        <Stat label="Needs me" icon={ClipboardList} value={summary.open_item_count} note={`across ${plural(summary.jobs_with_issues, 'job')}`} />
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
      {(data) =>
        viewer.owner ? (
          <MyOverview summary={data} owner={viewer.owner} />
        ) : viewer.home === 'finance' ? (
          <FinanceOverview summary={data} />
        ) : (
          <OperationsOverview summary={data} />
        )
      }
    </Loaded>
  )
}
