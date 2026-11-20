import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { COMMITMENT_KINDS, COMMITMENT_STATES } from '../lib/activity'
import { api } from '../lib/api'
import type { Commitment } from '../lib/api'
import { shortDate } from '../lib/format'
import { useViewer } from '../lib/viewer'
import { Tag } from './ItemTable'
import { Button, Empty } from './ui'

/** Everything a change to commitments can show up in. */
function useRefresh() {
  const client = useQueryClient()
  return () =>
    Promise.all(
      ['commitments', 'notes-reading', 'items', 'activity', 'job'].map((key) => client.invalidateQueries({ queryKey: [key] })),
    )
}

/**
 * Has the assistant read the notes it has not read yet. It is a button, never automatic,
 * because each read is a call to the model. A note already read is not sent again.
 */
export function ReadNotesButton() {
  const refresh = useRefresh()
  const reading = useQuery({ queryKey: ['notes-reading'], queryFn: api.noteReading })
  const read = useMutation({ mutationFn: api.readNotes, onSuccess: refresh })
  const unread = reading.data?.unread ?? 0

  return (
    <div className="flex items-center gap-3">
      {read.isError && <p className="text-[0.8125rem] text-neg">{read.error.message}</p>}
      {read.isSuccess && read.data.notes_read > 0 && (
        <p className="text-[0.8125rem] text-ink-2">
          Read {read.data.notes_read} notes, found {read.data.commitments_found}
        </p>
      )}
      <Button disabled={unread === 0 || read.isPending} onClick={() => read.mutate()}>
        {read.isPending ? 'Reading notes…' : unread === 0 ? 'All notes read' : `Read ${unread} new ${unread === 1 ? 'note' : 'notes'}`}
      </Button>
    </div>
  )
}

interface CommitmentTableProps {
  commitments: Commitment[]
  /** Shown on a list that spans jobs. Left out on a job's own page. */
  showJob?: boolean
  /** Left out when the list is of one kind only, where every row would repeat it. */
  showKind?: boolean
  empty?: string
}

/**
 * Promises and waits found in notes, the ones needing attention first, one fact per
 * column. Where each stands is worked out from the records; a person can mark one done.
 * Hover what was promised to read the note it came from.
 */
export function CommitmentTable({
  commitments,
  showJob = false,
  showKind = true,
  empty = 'No promises or waits found in the notes',
}: CommitmentTableProps) {
  const { viewer } = useViewer()
  const navigate = useNavigate()
  const refresh = useRefresh()
  const act = useMutation({
    mutationFn: ({ id, action }: { id: number; action: 'done' | 'reopen' }) => api.actOnCommitment(id, { action, actor: viewer.name }),
    onSuccess: refresh,
  })
  if (commitments.length === 0) return <Empty>{empty}</Empty>

  return (
    <div className="min-w-0 overflow-x-auto">
      <table className="data-table">
        <thead>
          <tr>
            <th>State</th>
            <th>Due</th>
            {showKind && <th>Kind</th>}
            <th>Who</th>
            <th>What</th>
            {showJob && <th className="max-md:hidden">Job</th>}
            <th className={showJob ? '@max-[70rem]:hidden' : '@max-[56rem]:hidden'}>Document</th>
            <th className="@max-[80rem]:hidden">Noted by</th>
            <th>
              <span className="sr-only">Mark done</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {commitments.map((c) => {
            const state = COMMITMENT_STATES[c.state]
            const opens = showJob && c.job_number
            const finished = c.state === 'done'
            return (
              <tr
                key={c.id}
                className={opens ? 'clickable' : undefined}
                onClick={opens ? () => navigate(`/jobs/${c.job_number}`) : undefined}
              >
                <td>
                  <Tag tone={state.tone}>{state.label}</Tag>
                </td>
                <td className="text-ink-2">{c.due_on ? shortDate(c.due_on) : 'No date'}</td>
                {showKind && <td className="text-ink-2">{COMMITMENT_KINDS[c.kind]}</td>}
                <td className="max-w-[12rem] truncate">{c.who}</td>
                <td className="w-full min-w-[12rem] py-2! whitespace-normal!" title={c.note}>
                  {c.what}
                </td>
                {showJob && <td className="max-w-[14rem] truncate text-ink-2 max-md:hidden">{c.job_name ?? ''}</td>}
                <td className={`font-mono text-[0.8125rem] text-ink-2 ${showJob ? '@max-[70rem]:hidden' : '@max-[56rem]:hidden'}`}>{c.document ?? ''}</td>
                <td className="text-ink-2 @max-[80rem]:hidden">{c.noted_by}</td>
                <td className="text-right">
                  {/* A payment promise that the payments show was kept needs no button. */}
                  {c.state !== 'kept' && (
                    <Button
                      disabled={act.isPending}
                      onClick={(event) => {
                        event.stopPropagation()
                        act.mutate({ id: c.id, action: finished ? 'reopen' : 'done' })
                      }}
                    >
                      {finished ? 'Reopen' : 'Mark done'}
                    </Button>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
