import { useMutation, useQueryClient } from '@tanstack/react-query'
import { RotateCcw, SquarePen } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import type { Issue, IssueSort, Order } from '../lib/api'
import { isoToday, money, shortDate } from '../lib/format'
import { useViewer } from '../lib/viewer'
import { UpdateDialog } from './UpdateDialog'
import { Empty, SortHeader } from './ui'

interface IssueTableProps {
  issues: Issue[]
  /** Hidden on a job's own page, where every row would repeat the same job. */
  showJob?: boolean
  /** Hidden when the viewer only sees their own issues. */
  showOwner?: boolean
  /** Shown on a list of resolved issues, in place of the dates. */
  showResolution?: boolean
  /** What to say when the list is empty. */
  empty?: string
  /** Given on a page that lets the reader sort. The headings then become buttons. */
  sorting?: { sort: IssueSort; order: Order; onSort: (sort: IssueSort, order: Order) => void }
}

const ICON = { size: '1rem', strokeWidth: 1.5, 'aria-hidden': true } as const

/**
 * One fact per column, one line per row: what kind of issue, how serious, which
 * document, when it was due and how late it is, which job, whose it is, how
 * much, and when someone said they would come back to it.
 * Clicking anywhere on a row opens the issue. The button on the right logs an
 * update; it never performs the action itself.
 */
export function IssueTable({
  issues,
  showJob = true,
  showOwner = true,
  showResolution = false,
  empty = 'Nothing needs attention here',
  sorting,
}: IssueTableProps) {
  const { viewer } = useViewer()
  const client = useQueryClient()
  const navigate = useNavigate()
  const [updating, setUpdating] = useState<Issue | null>(null)

  const reopen = useMutation({
    mutationFn: (issue: Issue) => api.actOnIssue(issue.id, { action: 'reopen', actor: viewer.name }),
    onSuccess: () => client.invalidateQueries(),
  })

  if (issues.length === 0) return <Empty>{empty}</Empty>

  // There is no room for the job's name until the screen is wide. Its ID stays,
  // and the row opens the issue, which names the job.
  const jobName = 'max-2xl:hidden'
  const today = isoToday()

  function heading(label: string, by: IssueSort, options: { numeric?: boolean; first?: Order; className?: string } = {}) {
    const { numeric = false, first, className = 'max-md:hidden' } = options
    if (!sorting) return <th className={`${numeric ? 'num ' : ''}${className}`}>{label}</th>
    return <SortHeader label={label} by={by} first={first} numeric={numeric} className={className} {...sorting} />
  }

  return (
    <>
      {/* Positioned, so the screen-reader-only heading inside cannot widen the page. */}
      <div className="relative overflow-x-auto">
        <table className="data-table dense">
          <thead>
            <tr>
              <th>Issue</th>
              {heading('Severity', 'severity')}
              <th className="max-md:hidden">Document</th>
              {showResolution ? (
                <th className="max-md:hidden">Resolution</th>
              ) : (
                <>
                  {heading('Due', 'due', { first: 'asc' })}
                  <th className="num max-md:hidden">Days late</th>
                </>
              )}
              {showJob && <th className="max-md:hidden">Job ID</th>}
              {showJob && <th className={jobName}>Job</th>}
              {showOwner && heading('Owner', 'owner', { first: 'asc' })}
              {heading('Amount', 'amount', { numeric: true })}
              {!showResolution && heading('Follow up', 'follow_up', { first: 'asc' })}
              <th className="num max-2xl:hidden">Notes</th>
              <th>
                <span className="sr-only">Action</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {issues.map((issue) => {
              const active = issue.status === 'open' || issue.status === 'assigned'
              const resolution = issue.resolution_note ?? 'No longer found in the source data'
              const followUpDue = issue.follow_up_on !== null && issue.follow_up_on <= today
              return (
                <tr key={issue.id} className="clickable" onClick={() => navigate(`/issues/${issue.id}`)}>
                  <td className="max-md:py-3 max-md:whitespace-normal!">
                    {/* The link keeps the row reachable by keyboard; the row click covers everywhere else. */}
                    <Link to={`/issues/${issue.id}`} className="font-medium" onClick={(e) => e.stopPropagation()}>
                      {issue.title}
                    </Link>
                    {/* A phone has room for one column, so the rest of the row is listed underneath. */}
                    <span className="block text-[0.8125rem] leading-4 text-ink-2 md:hidden">{active ? issue.summary : resolution}</span>
                    <span className="mt-1 block font-mono text-xs leading-4 text-muted md:hidden">
                      {[Number(issue.amount) > 0 ? money(issue.amount) : null, showJob ? issue.job_number : null]
                        .filter(Boolean)
                        .join('  ')}
                    </span>
                  </td>
                  <td className={`capitalize max-md:hidden ${issue.severity === 'high' ? '' : 'text-ink-2'}`}>{issue.severity}</td>
                  <td className="font-mono text-[0.8125rem] text-ink-2 max-md:hidden">{issue.document ?? ''}</td>
                  {showResolution ? (
                    <td className="text-ink-2 max-md:hidden">
                      <span className="block max-w-[20rem] truncate" title={resolution}>
                        {resolution}
                      </span>
                    </td>
                  ) : (
                    <>
                      <td className="text-ink-2 max-md:hidden">{issue.due_on ? shortDate(issue.due_on) : ''}</td>
                      <td className="num text-accent-ink max-md:hidden">{issue.days_late ?? ''}</td>
                    </>
                  )}
                  {showJob && <td className="font-mono text-[0.8125rem] text-ink-2 max-md:hidden">{issue.job_number ?? ''}</td>}
                  {showJob && (
                    <td className={jobName}>
                      {issue.job_name ? (
                        <span className="block max-w-[14rem] truncate 2xl:max-w-[24rem]" title={issue.job_name}>
                          {issue.job_name}
                        </span>
                      ) : (
                        <span className="text-muted">No job</span>
                      )}
                    </td>
                  )}
                  {showOwner && <td className="text-ink-2 max-md:hidden">{issue.owner}</td>}
                  <td className="num max-md:hidden">{Number(issue.amount) > 0 ? money(issue.amount) : ''}</td>
                  {!showResolution && (
                    <td className={`max-md:hidden ${followUpDue ? 'text-accent-ink' : 'text-ink-2'}`}>
                      {issue.follow_up_on ? shortDate(issue.follow_up_on) : ''}
                    </td>
                  )}
                  <td className="num max-2xl:hidden">{issue.note_count || ''}</td>
                  <td className="w-10 text-right max-md:pt-3 max-md:align-top">
                    <button
                      type="button"
                      title={active ? 'Log update' : 'Reopen'}
                      aria-label={`${active ? 'Log update on' : 'Reopen'} ${issue.title}${issue.document ? `, ${issue.document}` : ''}`}
                      disabled={!active && reopen.isPending}
                      className="inline-grid size-8 place-items-center rounded-lg text-muted transition-colors duration-150 ease-out hover:bg-card hover:text-ink hover:ring-1 hover:ring-hair disabled:opacity-50"
                      onClick={(event) => {
                        // The button acts on the issue; it must not also open it.
                        event.stopPropagation()
                        if (active) setUpdating(issue)
                        else reopen.mutate(issue)
                      }}
                    >
                      {active ? <SquarePen {...ICON} /> : <RotateCcw {...ICON} />}
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {updating && <UpdateDialog issue={updating} onClose={() => setUpdating(null)} />}
    </>
  )
}
