import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import type { Issue } from '../lib/api'
import { money, shortDate } from '../lib/format'
import { useViewer } from '../lib/viewer'
import { UpdateDialog } from './UpdateDialog'
import { Button, Empty } from './ui'

interface IssueTableProps {
  issues: Issue[]
  /** Hidden on a job's own page, where every row would repeat the same job. */
  showJob?: boolean
  /** Hidden when the viewer only sees their own issues. */
  showOwner?: boolean
  /** Shown on a list of resolved issues, in place of the due date. */
  showResolution?: boolean
  /** What to say when the list is empty. */
  empty?: string
}

/**
 * One fact per column, one line per row: what kind of issue, which document,
 * when it is due, which job, how much, and how many notes people have left.
 * Clicking anywhere on a row opens the issue. The button on the right logs an
 * update; it never performs the action itself.
 */
export function IssueTable({
  issues,
  showJob = true,
  showOwner = true,
  showResolution = false,
  empty = 'Nothing needs attention here',
}: IssueTableProps) {
  const { viewer } = useViewer()
  const client = useQueryClient()
  const navigate = useNavigate()
  const [resolving, setResolving] = useState<Issue | null>(null)

  const reopen = useMutation({
    mutationFn: (issue: Issue) => api.actOnIssue(issue.id, { action: 'reopen', actor: viewer.name }),
    onSuccess: () => client.invalidateQueries(),
  })

  if (issues.length === 0) return <Empty>{empty}</Empty>

  // With an owner column as well, there is no room for the job's name until the
  // screen is wide. Its ID stays, and the row opens the issue, which names the job.
  const jobName = showOwner ? 'max-2xl:hidden' : 'max-md:hidden'

  return (
    <>
      <div className="overflow-x-auto">
        <table className="data-table">
          <thead>
            <tr>
              <th>Issue</th>
              <th className="max-md:hidden">Document</th>
              {showResolution ? <th className="max-md:hidden">Resolution</th> : <th className="max-md:hidden">Due</th>}
              {showJob && <th className="max-md:hidden">Job ID</th>}
              {showJob && <th className={jobName}>Job</th>}
              {showOwner && <th className="max-md:hidden">Owner</th>}
              <th className="num max-md:hidden">Amount</th>
              <th className="num max-md:hidden">Notes</th>
              <th>
                <span className="sr-only">Action</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {issues.map((issue) => {
              const active = issue.status === 'open' || issue.status === 'assigned'
              const resolution = issue.resolution_note ?? 'No longer found in the source data'
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
                  <td className="font-mono text-[0.8125rem] text-ink-2 max-md:hidden">{issue.document ?? ''}</td>
                  {showResolution ? (
                    <td className="text-ink-2 max-md:hidden">
                      <span className="block max-w-[20rem] truncate" title={resolution}>
                        {resolution}
                      </span>
                    </td>
                  ) : (
                    <td className="text-ink-2 max-md:hidden">{issue.due_on ? shortDate(issue.due_on) : ''}</td>
                  )}
                  {showJob && <td className="font-mono text-[0.8125rem] text-ink-2 max-md:hidden">{issue.job_number ?? ''}</td>}
                  {showJob && (
                    <td className={jobName}>
                      {issue.job_name ? (
                        <span className="block max-w-[8rem] truncate 2xl:max-w-[26.25rem]" title={issue.job_name}>
                          {issue.job_name}
                        </span>
                      ) : (
                        <span className="text-muted">No job</span>
                      )}
                    </td>
                  )}
                  {showOwner && <td className="text-ink-2 max-md:hidden">{issue.owner}</td>}
                  <td className="num max-md:hidden">{Number(issue.amount) > 0 ? money(issue.amount) : ''}</td>
                  <td className="num max-md:hidden">{issue.note_count || ''}</td>
                  <td className="w-32 text-right max-md:pt-3 max-md:align-top">
                    <Button
                      className="w-28"
                      disabled={!active && reopen.isPending}
                      onClick={(event) => {
                        // The button acts on the issue; it must not also open it.
                        event.stopPropagation()
                        if (active) setResolving(issue)
                        else reopen.mutate(issue)
                      }}
                    >
                      {active ? 'Log update' : 'Reopen'}
                    </Button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {resolving && <UpdateDialog issue={resolving} onClose={() => setResolving(null)} />}
    </>
  )
}
