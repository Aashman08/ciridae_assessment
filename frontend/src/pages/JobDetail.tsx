import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ActivityTable } from '../components/ActivityTable'
import { CommitmentTable, ReadNotesButton } from '../components/Commitments'
import { NextSteps } from '../components/NextSteps'
import { Card, CardHead, Empty, Facts, Loaded, PageHead } from '../components/ui'
import { api } from '../lib/api'
import type { CostBasis, FigureOption, JobDetail as Job, Line, RevenueBasis } from '../lib/api'
import { useAssistant } from '../lib/assistant'
import { money, percent, shortDate, stage, words } from '../lib/format'
import { buttonClass } from '../lib/styles'

interface FigurePickerProps<Basis extends string> {
  title: string
  name: string
  options: FigureOption<Basis>[]
  value: Basis
  onChange: (basis: Basis) => void
}

/** The figures one side of the profit sum could use, side by side. Pick one. */
function FigurePicker<Basis extends string>({ title, name, options, value, onChange }: FigurePickerProps<Basis>) {
  return (
    <Card className="flex flex-col gap-1 p-2">
      <h2 className="px-3 pt-3 pb-1 font-medium">{title}</h2>
      <div role="radiogroup" aria-label={title} className="flex flex-col gap-1">
        {options.map((option) => (
          <label
            key={option.basis}
            className="grid cursor-pointer grid-cols-[1rem_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 rounded-lg p-3 transition-colors duration-150 ease-out hover:bg-brand-soft/30 has-checked:bg-brand-soft/50 has-checked:ring-1 has-checked:ring-brand/40 has-checked:ring-inset has-focus-visible:outline-2 has-focus-visible:outline-accent-ink"
          >
            <input
              type="radio"
              name={name}
              value={option.basis}
              checked={option.basis === value}
              onChange={() => onChange(option.basis)}
              className="peer sr-only"
            />
            <span className="size-4 rounded-full ring-[1.5px] ring-muted ring-inset peer-checked:ring-[0.3125rem] peer-checked:ring-brand" />
            <span className="font-medium">{option.label}</span>
            <span className="font-mono tabular-nums">{money(option.amount)}</span>
            <span className="col-span-2 col-start-2 text-xs leading-4 text-muted">{option.description}</span>
          </label>
        ))}
      </div>
    </Card>
  )
}

function ProfitResult({ job }: { job: Job }) {
  const { profit } = job
  const margin = profit.margin_pct === null ? null : Number(profit.margin_pct)
  const planned = Number(profit.planned_margin_pct ?? 0)
  // Three points under plan is where a margin starts to deserve a second look.
  const behind = margin !== null && margin < planned - 3

  return (
    <Card className="flex flex-col gap-3 p-5">
      <span className="text-ink-2">Profit with these two figures</span>
      <span className={`text-[2rem] leading-8 font-medium tabular-nums ${Number(profit.profit) < 0 ? 'text-neg' : ''}`}>
        {money(profit.profit)}
      </span>
      <div className="pt-2">
        <Facts
          rows={[
            [
              'Margin',
              <span key="margin" className={behind ? 'text-accent-ink' : ''}>{margin === null ? 'No revenue yet' : percent(profit.margin_pct)}</span>,
              margin !== null,
            ],
            ['Planned margin', percent(profit.planned_margin_pct)],
            ['Contract', money(job.contract_value)],
            ['Budget', money(job.budget)],
          ]}
        />
      </div>
    </Card>
  )
}

function SystemFacts({ job }: { job: Job }) {
  const heading = 'pb-2 text-[0.8125rem] font-medium'
  return (
    <Card>
      <CardHead title="What each system says" />
      <div className="grid grid-cols-1 gap-x-8 gap-y-6 px-5 pb-5 md:grid-cols-3">
        <div>
          <h3 className={heading}>CRM</h3>
          <Facts
            rows={[
              ['Won', shortDate(job.won_on)],
              ['Estimated value', money(job.estimated_value)],
              ['Account executive', job.account_executive ?? 'None'],
            ]}
          />
        </div>
        <div>
          <h3 className={heading}>Project system</h3>
          <Facts
            rows={[
              ['Stage', stage(job.stage)],
              ['On site', shortDate(job.on_site_on)],
              ['Planned finish', shortDate(job.planned_finish_on)],
              ['Completed', shortDate(job.completed_on)],
              ['Closed', shortDate(job.closed_on)],
              ['Cost logged', money(job.ops_cost)],
            ]}
          />
        </div>
        <div>
          <h3 className={heading}>Accounting</h3>
          <Facts
            rows={[
              ['Revenue in ledger', money(job.ledger_revenue)],
              ['Cost in ledger', money(job.ledger_cost)],
              ['Invoices sent', money(job.sent)],
              ['Still owed', money(job.owed)],
              ['Vendor bills unpaid', money(job.unpaid_bills)],
            ]}
          />
        </div>
      </div>
    </Card>
  )
}

interface DocumentsProps {
  title: string
  lines: Line[]
  empty: string
  /** Bills name their vendor. A job's invoices all go to its one customer, so they do not repeat it. */
  vendor?: boolean
}

/** A job's invoices or bills. Clicking one opens it laid out as a document. */
function Documents({ title, lines, empty, vendor = false }: DocumentsProps) {
  const { view, show } = useAssistant()
  const open = (line: Line) => show({ kind: 'document', lineId: line.id, documentKind: vendor ? 'vendor_bill' : 'customer_invoice' })
  const showing = view?.kind === 'document' ? view.lineId : null
  return (
    <Card>
      <CardHead title={title} />
      {lines.length === 0 ? (
        <Empty>{empty}</Empty>
      ) : (
        <div className="overflow-x-auto">
          <table className="data-table">
            <thead>
              <tr>
                <th>Number</th>
                {vendor && <th>Vendor</th>}
                <th>Status</th>
                <th>Due</th>
                <th className="num">Amount</th>
                {!vendor && <th className="num">Paid</th>}
              </tr>
            </thead>
            <tbody>
              {lines.map((line) => (
                <tr
                  key={line.id}
                  className={`clickable ${showing === line.id ? 'bg-brand-soft/50' : ''}`}
                  aria-current={showing === line.id || undefined}
                  onClick={() => open(line)}
                >
                  <td className="font-mono text-[0.8125rem]">
                    {/* The button keeps the row reachable by keyboard; the row click covers everywhere else. */}
                    <button
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation()
                        open(line)
                      }}
                    >
                      {line.doc_number}
                    </button>
                  </td>
                  {vendor && <td>{line.company ?? line.description}</td>}
                  <td className="text-ink-2">{words(line.status)}</td>
                  <td className="text-ink-2">{shortDate(line.due_date)}</td>
                  <td className="num">{money(line.amount)}</td>
                  {!vendor && <td className="num">{money(line.paid_amount)}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}

/** Promises and waits the assistant found in this job's notes, and where each stands. */
function JobCommitments({ jobNumber }: { jobNumber: string }) {
  const commitments = useQuery({
    queryKey: ['commitments', 'job', jobNumber],
    queryFn: () => api.commitments({ job: jobNumber, state: 'all', limit: 100 }),
  })
  return (
    <Card>
      <CardHead title="Promises and waits from notes">
        <ReadNotesButton />
      </CardHead>
      <Loaded query={commitments}>
        {(page) => <CommitmentTable commitments={page.data} empty="No promises or waits found in this job's notes" />}
      </Loaded>
    </Card>
  )
}

const ACTIVITY_SHOWN = 50

/**
 * Everything written about the job and done on it, in one list: notes from the project
 * system and accounting, updates logged here, and what happened to each of its issues.
 */
function JobActivity({ jobNumber }: { jobNumber: string }) {
  const activity = useQuery({
    queryKey: ['activity', 'job', jobNumber],
    queryFn: () => api.activity({ job: jobNumber, limit: ACTIVITY_SHOWN }),
  })
  return (
    <Card>
      <CardHead title="Notes and activity">
        {activity.data && activity.data.total > ACTIVITY_SHOWN && (
          <Link to={`/activity?job=${jobNumber}`} className={buttonClass()}>
            All {activity.data.total}
          </Link>
        )}
      </CardHead>
      <Loaded query={activity}>{(page) => <ActivityTable entries={page.data} empty="Nothing written or done on this job yet" />}</Loaded>
    </Card>
  )
}

export function JobDetail() {
  const { jobNumber = '' } = useParams()
  const [revenue, setRevenue] = useState<RevenueBasis>('ledger')
  const [cost, setCost] = useState<CostBasis>('ledger')

  // The server works out profit for the chosen pair, so the formula lives in one place.
  // Keeping the previous answer on screen stops the page flashing while the next one loads.
  const job = useQuery({
    queryKey: ['job', jobNumber, revenue, cost],
    queryFn: () => api.job(jobNumber, revenue, cost),
    placeholderData: keepPreviousData,
  })

  return (
    <Loaded query={job}>
      {(data) => (
        <>
          <PageHead
            title={data.name}
            sub={
              <span className="flex flex-wrap gap-x-4 gap-y-1">
                <span className="font-mono text-[0.8125rem]">{data.job_number}</span>
                <span>{data.customer}</span>
                <span>{stage(data.stage)}</span>
                <span>{data.branch}</span>
                <span className={data.ops_manager ? '' : 'text-accent-ink'}>{data.ops_manager ?? 'No ops manager'}</span>
              </span>
            }
          />

          <div className="grid grid-cols-1 gap-4 @[58rem]:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_18.75rem] @[80rem]:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_25rem]">
            <FigurePicker title="Revenue" name="revenue" options={data.revenue_options} value={revenue} onChange={setRevenue} />
            <FigurePicker title="Cost" name="cost" options={data.cost_options} value={cost} onChange={setCost} />
            <ProfitResult job={data} />
          </div>

          <SystemFacts job={data} />

          <NextSteps jobNumber={data.job_number} items={data.items} />

          <div className="grid grid-cols-1 gap-4 @[80rem]:grid-cols-2">
            <Documents title="Customer invoices" lines={data.invoices} empty="No invoices yet" />
            <Documents title="Vendor bills" lines={data.vendor_bills} empty="No vendor bills on this job" vendor />
          </div>

          <JobCommitments jobNumber={data.job_number} />

          <JobActivity jobNumber={data.job_number} />
        </>
      )}
    </Loaded>
  )
}
