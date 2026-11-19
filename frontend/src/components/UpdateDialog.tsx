import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { api } from '../lib/api'
import type { Issue } from '../lib/api'
import { money, shortDate } from '../lib/format'
import { useViewer } from '../lib/viewer'
import { Button, Facts } from './ui'

interface UpdateDialogProps {
  issue: Issue
  onClose: () => void
}

/**
 * Where someone writes down what they have already done about an issue.
 *
 * It does not do the thing for them: no email goes out and no invoice or bill
 * changes. Saving a note keeps the issue open, because a phone call about an
 * unpaid invoice does not make it paid. Resolving is a separate, deliberate choice.
 */
export function UpdateDialog({ issue, onClose }: UpdateDialogProps) {
  const { viewer } = useViewer()
  const client = useQueryClient()
  const dialog = useRef<HTMLDialogElement>(null)
  const [note, setNote] = useState('')
  const written = note.trim()

  // A native dialog gives focus trapping, Escape to close and a backdrop for free.
  useEffect(() => {
    dialog.current?.showModal()
  }, [])

  const save = useMutation({
    mutationFn: (action: 'comment' | 'resolve') => api.actOnIssue(issue.id, { action, actor: viewer.name, note: written }),
    onSuccess: async () => {
      // A note changes the count on the row; resolving changes totals on every screen.
      await client.invalidateQueries()
      onClose()
    },
  })

  function saveNote(event: FormEvent) {
    event.preventDefault()
    if (written) save.mutate('comment')
  }

  const facts: [string, string][] = [['Issue', issue.title]]
  if (issue.document) facts.push(['Document', issue.document])
  if (issue.due_on) facts.push(['Due', shortDate(issue.due_on)])
  if (issue.job_name) facts.push(['Job', issue.job_name])
  if (issue.job_number) facts.push(['Job ID', issue.job_number])
  if (Number(issue.amount) > 0) facts.push(['Amount', money(issue.amount)])
  facts.push(['Owner', issue.owner])

  return (
    <dialog
      ref={dialog}
      onClose={onClose}
      aria-labelledby="update-title"
      className="m-auto w-[min(32rem,calc(100vw-2rem))] rounded-2xl border border-hair bg-card p-0 text-ink shadow-float backdrop:bg-scrim"
    >
      <form onSubmit={saveNote} className="flex flex-col gap-5 p-5">
        <div>
          <h2 id="update-title" className="text-base font-medium">
            Log an update
          </h2>
          <p className="mt-1 text-[0.8125rem] leading-5 text-ink-2">
            Write down what you have already done, such as a call or an email. This does not contact anyone or change the
            invoice or bill.
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
            required
            autoFocus
            placeholder="Called their payables desk. Payment goes out Friday"
            className="resize-none rounded-lg border border-hair bg-bg px-3 py-2 placeholder:text-muted"
          />
        </label>

        {save.isError && <p className="text-[0.8125rem] text-neg">{save.error.message}</p>}

        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap justify-end gap-2">
            <Button onClick={() => dialog.current?.close()}>Cancel</Button>
            <Button disabled={!written || save.isPending} onClick={() => save.mutate('resolve')}>
              Save and resolve
            </Button>
            <Button variant="primary" type="submit" disabled={!written || save.isPending}>
              {save.isPending ? 'Saving' : 'Save note'}
            </Button>
          </div>
          <p className="text-right text-xs leading-4 text-muted">
            A note keeps the issue open. Resolve it only once the problem itself is fixed
          </p>
        </div>
      </form>
    </dialog>
  )
}
