import { useNavigate } from 'react-router-dom'
import { what, who } from '../lib/activity'
import type { ActivityEntry } from '../lib/api'
import { dateTime } from '../lib/format'
import { Empty } from './ui'

interface ActivityTableProps {
  entries: ActivityEntry[]
  /** Shown on a list that spans jobs. Left out on a job's own page, where every row would repeat it. */
  showJob?: boolean
  /** Left out where every row is a note, which has no check. */
  showCheck?: boolean
  empty?: string
}

/**
 * Notes and actions, newest first, one fact per column: when, who, where it came
 * from, what happened, which check and which document it concerns, and the note.
 * On a list that spans jobs, a row with a job opens that job.
 */
export function ActivityTable({ entries, showJob = false, showCheck = true, empty = 'Nothing has happened here yet' }: ActivityTableProps) {
  const navigate = useNavigate()
  if (entries.length === 0) return <Empty>{empty}</Empty>

  return (
    <div className="min-w-0 overflow-x-auto">
      <table className="data-table">
        <thead>
          <tr>
            <th>When</th>
            <th>Who</th>
            <th>What</th>
            {showJob && <th className="max-md:hidden">Job</th>}
            {/* Narrower screens drop the check, then the document, so the note keeps its room. */}
            {showCheck && <th className="@max-[63rem]:hidden">Check</th>}
            <th className="@max-[50rem]:hidden">Document</th>
            <th>Note</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry, index) => {
            const opens = showJob && entry.job_number
            return (
              <tr
                key={`${entry.at}-${entry.kind}-${index}`}
                className={opens ? 'clickable' : undefined}
                onClick={opens ? () => navigate(`/jobs/${entry.job_number}`) : undefined}
              >
                <td className="text-ink-2">{dateTime(entry.at)}</td>
                <td>{who(entry.by)}</td>
                <td>{what(entry.kind, entry.source)}</td>
                {showJob && <td className="max-w-[14rem] truncate text-ink-2 max-md:hidden">{entry.job_name ?? ''}</td>}
                {showCheck && <td className="max-w-[13rem] truncate text-ink-2 @max-[63rem]:hidden">{entry.about ?? ''}</td>}
                <td className="font-mono text-[0.8125rem] text-ink-2 @max-[50rem]:hidden">{entry.document ?? ''}</td>
                {/* A note can run to a few lines; it is the one cell allowed to wrap, and takes the room left. */}
                <td className="w-full min-w-[14rem] py-2! whitespace-normal! text-ink-2">{entry.text ?? ''}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
