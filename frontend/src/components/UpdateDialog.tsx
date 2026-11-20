import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { api } from '../lib/api'
import type { Issue, IssueUpdate } from '../lib/api'
import { money, shortDate } from '../lib/format'
import { useViewer } from '../lib/viewer'
import { Button, Facts, Select } from './ui'
import type { SelectOption } from './ui'

interface UpdateDialogProps {
  issue: Issue
  onClose: () => void
}

// People are offered under the role that would normally bring an issue to them.
const GROUPS: [role: string, label: string][] = [
  ['ops_manager', 'Ops managers'],
  ['account_executive', 'Account executives'],
  ['finance', 'Finance'],
]

const FIELD = 'h-9 rounded-lg border border-hair bg-bg px-3 text-ink'

/**
 * Where someone records what they have done about an issue, hands it to
 * someone else, or sets a date to come back to it.
 *
 * It does not do the thing for them: no email goes out and no invoice or bill
 * changes. Saving keeps the issue open, because a phone call about an unpaid
 * invoice does not make it paid. Resolving is a separate, deliberate choice.
 */
export function UpdateDialog({ issue, onClose }: UpdateDialogProps) {
  const { viewer } = useViewer()
  const client = useQueryClient()
  const dialog = useRef<HTMLDialogElement>(null)
  const [note, setNote] = useState('')
  const [owner, setOwner] = useState(issue.owner)
  const [followUp, setFollowUp] = useState(issue.follow_up_on ?? '')
  const written = note.trim()

  const people = useQuery({ queryKey: ['people'], queryFn: api.people, staleTime: Infinity })
  // Whoever has it now is always offered, even if they are not on any job.
  const owners: SelectOption[] = GROUPS.flatMap(([role, group]) =>
    (people.data ?? []).filter((person) => person.roles[0] === role).map((person) => ({ value: person.name, label: person.name, group })),
  )
  if (!owners.some((option) => option.value === issue.owner)) owners.unshift({ value: issue.owner, label: issue.owner })

  const ownerChanged = owner !== issue.owner
  const dateChanged = followUp !== (issue.follow_up_on ?? '')
  const changed = Boolean(written) || ownerChanged || dateChanged

  // A native dialog gives focus trapping, Escape to close and a backdrop for free.
  useEffect(() => {
    dialog.current?.showModal()
  }, [])

  const save = useMutation({
    mutationFn: (action: 'update' | 'resolve') => {
      const body: IssueUpdate = { action, actor: viewer.name }
      if (written) body.note = written
      if (action === 'update') {
        if (ownerChanged) body.assignee = owner
        if (dateChanged && followUp) body.follow_up_on = followUp
        if (dateChanged && !followUp) body.clear_follow_up = true
      }
      return api.actOnIssue(issue.id, body)
    },
    onSuccess: async () => {
      // An update changes the row; resolving changes totals on every screen.
      await client.invalidateQueries()
      onClose()
    },
  })

  function submit(event: FormEvent) {
    event.preventDefault()
    if (changed) save.mutate('update')
  }

  const facts: [string, string][] = [['Issue', issue.title]]
  if (issue.document) facts.push(['Document', issue.document])
  if (issue.due_on) facts.push(['Due', shortDate(issue.due_on)])
  if (issue.job_name) facts.push(['Job', issue.job_name])
  if (issue.job_number) facts.push(['Job ID', issue.job_number])
  if (Number(issue.amount) > 0) facts.push(['Amount', money(issue.amount)])

  return (
    <dialog
      ref={dialog}
      onClose={onClose}
      aria-labelledby="update-title"
      className="m-auto max-h-[calc(100dvh-2rem)] w-[min(34rem,calc(100vw-2rem))] overflow-y-auto rounded-2xl border border-hair bg-card p-0 text-ink shadow-float backdrop:bg-scrim"
    >
      <form onSubmit={submit} className="flex flex-col gap-5 p-5">
        <div>
          <h2 id="update-title" className="text-base font-medium">
            Log an update
          </h2>
          <p className="mt-1 text-[0.8125rem] leading-5 text-ink-2">
            Record what you have done, hand the issue to someone, or set a date to come back to it. This does not contact
            anyone or change the invoice or bill.
          </p>
        </div>

        <div className="rounded-lg bg-raised p-3">
          <Facts rows={facts} />
        </div>

        <div>
          <p className="text-[0.8125rem] text-ink-2">Suggested next step</p>
          <p className="mt-1">{issue.next_step}</p>
        </div>

        <label className="flex flex-col gap-2">
          <span className="text-[0.8125rem] text-ink-2">What you did</span>
          <textarea
            id="update-note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={3}
            autoFocus
            placeholder="Called their payables desk. Payment goes out Friday"
            className="resize-none rounded-lg border border-hair bg-bg px-3 py-2 placeholder:text-muted"
          />
        </label>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Select label="Owner" layout="stacked" value={owner} onChange={setOwner} options={owners} />
          <label className="flex min-w-0 flex-col gap-2">
            <span className="text-[0.8125rem] text-ink-2">Follow up on</span>
            <input type="date" value={followUp} onChange={(e) => setFollowUp(e.target.value)} className={FIELD} />
          </label>
        </div>

        {save.isError && <p className="text-[0.8125rem] text-neg">{save.error.message}</p>}

        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap justify-end gap-2">
            <Button onClick={() => dialog.current?.close()}>Cancel</Button>
            <Button disabled={!written || save.isPending} onClick={() => save.mutate('resolve')}>
              Save and resolve
            </Button>
            <Button variant="primary" type="submit" disabled={!changed || save.isPending}>
              {save.isPending ? 'Saving' : 'Save'}
            </Button>
          </div>
          <p className="text-right text-xs leading-4 text-muted">
            Saving keeps the issue open. Resolve it only once the problem itself is fixed, with a note saying how
          </p>
        </div>
      </form>
    </dialog>
  )
}
