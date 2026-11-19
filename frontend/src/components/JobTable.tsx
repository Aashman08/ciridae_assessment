import { Link, useNavigate } from 'react-router-dom'
import type { JobSummary } from '../lib/api'
import { money, stage } from '../lib/format'
import { Empty } from './ui'

interface JobTableProps {
  jobs: JobSummary[]
  /** The full table shows stage and the figures from each system. The short one names the biggest issue instead. */
  full?: boolean
  /** Hidden when every row would name the same person. */
  showOwner?: boolean
}

export function JobTable({ jobs, full = false, showOwner = true }: JobTableProps) {
  const navigate = useNavigate()
  if (jobs.length === 0) return <Empty>No jobs match this filter</Empty>

  return (
    <div className="overflow-x-auto">
      <table className="data-table">
        <thead>
          <tr>
            <th>Job ID</th>
            <th>Job</th>
            {full && <th>Stage</th>}
            {showOwner && <th>Owner</th>}
            {full && <th className="num">Contract</th>}
            {full && <th className="num max-2xl:hidden">Invoiced</th>}
            {full && <th className="num max-2xl:hidden">Collected</th>}
            <th className="num">Owed</th>
            {full && <th className="num">Cost, ops log</th>}
            {full && <th className="num">Cost, ledger</th>}
            <th className="num">Issues</th>
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
                  className={`block truncate 2xl:max-w-[30rem] ${full ? 'max-w-[12.25rem]' : 'max-w-[22.5rem]'}`}
                  title={job.name}
                  onClick={(e) => e.stopPropagation()}
                >
                  {job.name}
                </Link>
              </td>
              {full && <td className="text-ink-2">{stage(job.stage)}</td>}
              {showOwner && (
                <td className={job.ops_manager ? 'text-ink-2' : 'text-accent-ink'}>{job.ops_manager ?? 'Unassigned'}</td>
              )}
              {full && <td className="num">{money(job.contract_value)}</td>}
              {full && <td className="num max-2xl:hidden">{money(job.invoiced)}</td>}
              {full && <td className="num max-2xl:hidden">{money(job.collected)}</td>}
              <td className="num">{money(job.owed)}</td>
              {full && <td className="num">{money(job.ops_cost)}</td>}
              {full && <td className="num">{money(job.ledger_cost)}</td>}
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
