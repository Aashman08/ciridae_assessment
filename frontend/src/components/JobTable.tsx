import { Link, useNavigate } from 'react-router-dom'
import type { JobSort, JobSummary, Order } from '../lib/api'
import { money, percent, stage } from '../lib/format'
import { Empty, SortHeader } from './ui'

interface JobTableProps {
  jobs: JobSummary[]
  /** The full table shows what each job earned. The short one shows what it is owed and its biggest issue.
   *  Everything else about a job is on its own page. */
  full?: boolean
  /** Hidden when every row would name the same person. */
  showOwner?: boolean
  /** Given on a page that lets the reader sort. The headings then become buttons. */
  sorting?: { sort: JobSort; order: Order; onSort: (sort: JobSort, order: Order) => void }
}

/** A margin more than two points under plan is worth a second look. */
function belowPlan(job: JobSummary): boolean {
  if (job.ledger_margin_pct === null || job.planned_margin_pct === null) return false
  return Number(job.ledger_margin_pct) < Number(job.planned_margin_pct) - 2
}

/** A figure that is nothing yet is left blank, so the rows with something in them stand out. */
function amount(value: string): string {
  return Number(value) === 0 ? '' : money(value)
}

export function JobTable({ jobs, full = false, showOwner = true, sorting }: JobTableProps) {
  const navigate = useNavigate()
  if (jobs.length === 0) return <Empty>No jobs match this filter</Empty>

  function heading(label: string, by: JobSort, options: { numeric?: boolean; first?: Order; className?: string } = {}) {
    const { numeric = false, first, className } = options
    if (!sorting) return <th className={[numeric ? 'num' : '', className ?? ''].join(' ').trim() || undefined}>{label}</th>
    return <SortHeader label={label} by={by} first={first} numeric={numeric} className={className} {...sorting} />
  }

  return (
    <div className="overflow-x-auto">
      <table className={full ? 'data-table dense' : 'data-table'}>
        <thead>
          <tr>
            {heading('Job ID', 'job_number', { first: 'asc' })}
            {heading('Job', 'name', { first: 'asc' })}
            {full && <th>Stage</th>}
            {showOwner && <th>Ops manager</th>}
            {full && heading('Revenue', 'revenue', { numeric: true })}
            {full && heading('Cost', 'cost', { numeric: true })}
            {full && heading('Profit', 'profit', { numeric: true })}
            {full && heading('Margin', 'margin', { numeric: true })}
            {!full && heading('Owed', 'owed', { numeric: true })}
            {heading('Issues', 'issues', { numeric: true })}
            {!full && <th>Biggest issue</th>}
          </tr>
        </thead>
        <tbody>
          {jobs.map((job) => (
            <tr key={job.job_number} className="clickable" onClick={() => navigate(`/jobs/${job.job_number}`)}>
              <td className="font-mono text-[0.8125rem] text-ink-2">{job.job_number}</td>
              <td>
                {/* The link makes the row reachable by keyboard; the row click is a convenience. */}
                <Link
                  to={`/jobs/${job.job_number}`}
                  className={`block truncate ${full ? 'max-w-[16rem] @[72rem]:max-w-[30rem]' : 'max-w-[22.5rem]'}`}
                  title={job.name}
                  onClick={(e) => e.stopPropagation()}
                >
                  {job.name}
                </Link>
              </td>
              {full && <td className="text-ink-2">{stage(job.stage)}</td>}
              {showOwner && (
                <td className={job.ops_manager ? 'text-ink-2' : 'text-accent-ink'}>{job.ops_manager ?? 'None assigned'}</td>
              )}
              {full && <td className="num">{amount(job.ledger_revenue)}</td>}
              {full && <td className="num">{amount(job.ledger_cost)}</td>}
              {full && (
                <td className={`num ${Number(job.ledger_profit) < 0 ? 'text-neg' : ''}`}>{amount(job.ledger_profit)}</td>
              )}
              {full && (
                <td className={`num ${belowPlan(job) ? 'text-accent-ink' : ''}`}>{percent(job.ledger_margin_pct)}</td>
              )}
              {!full && <td className="num">{amount(job.owed)}</td>}
              <td className="num">{job.issue_count || ''}</td>
              {!full && (
                <td className="text-ink-2">
                  <span className="block max-w-[17.5rem] truncate">{job.top_issue?.title ?? ''}</span>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
