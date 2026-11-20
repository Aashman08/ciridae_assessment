import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { api } from '../lib/api'
import type { Item } from '../lib/api'
import { money, shortDate } from '../lib/format'
import { useItemAction } from '../lib/items'
import { Button, Facts, Select } from './ui'
import type { SelectOption } from './ui'

interface UpdateDialogProps {
  item: Item
  /** Text to start the note with, such as the assistant's reason for dismissing. */
  note?: string
  /** What the person came here to do. It decides which button is the main one. */
  purpose?: 'update' | 'assign' | 'dismiss'
  onClose: () => void
}

// People are offered under the role that would normally bring an item to them.
const GROUPS: [role: string, label: string][] = [
  ['ops_manager', 'Ops managers'],
  ['account_executive', 'Account executives'],
  ['finance', 'Finance'],
]

const FIELD = 'h-9 rounded-lg border border-hair bg-bg px-3 text-ink'

const TITLES = { update: 'Log an update', assign: 'Assign an owner', dismiss: 'Dismiss as expected' } as const

/**
 * Where someone records what they have done about an item, hands it to someone
 * else, sets a date to come back to it, or closes it.
 *
 * It does not do the thing for them: no invoice or bill changes. Saving keeps
 * the item open, because a phone call about an unpaid invoice does not make it
 * paid. Resolving and dismissing are separate, deliberate choices.
 */
export function UpdateDialog({ item, note: startingNote = '', purpose = 'update', onClose }: UpdateDialogProps) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [note, setNote] = useState(startingNote)
  const [owner, setOwner] = useState(item.owner)
  const [followUp, setFollowUp] = useState(item.follow_up_on ?? '')
  const written = note.trim()

  const people = useQuery({ queryKey: ['people'], queryFn: api.people, staleTime: Infinity })
  // Whoever has it now is always offered, even if they are not on any job.
  const owners: SelectOption[] = GROUPS.flatMap(([role, group]) =>
    (people.data ?? []).filter((person) => person.roles[0] === role).map((person) => ({ value: person.name, label: person.name, group })),
  )
  if (!owners.some((option) => option.value === item.owner)) owners.unshift({ value: item.owner, label: item.owner })

  const ownerChanged = owner !== item.owner
  const dateChanged = followUp !== (item.follow_up_on ?? '')
  const changed = Boolean(written) || ownerChanged || dateChanged

  // A native dialog gives focus trapping, Escape to close and a backdrop for free.
  useEffect(() => {
    dialog.current?.showModal()
  }, [])

  const act = useItemAction()

  function save(action: 'update' | 'resolve' | 'dismiss') {
    act.mutate(
      {
        item,
        action,
        note: written || undefined,
        ...(action === 'update' && {
          assignee: ownerChanged ? owner : undefined,
          follow_up_on: dateChanged && followUp ? followUp : undefined,
          clear_follow_up: dateChanged && !followUp ? true : undefined,
        }),
      },
      { onSuccess: onClose },
    )
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    if (purpose === 'dismiss') {
      if (written) save('dismiss')
    } else if (changed) save('update')
  }

  const facts: [string, string][] = [['What', item.title]]
  if (item.document) facts.push(['Document', item.document])
  if (item.due_on) facts.push(['Due', shortDate(item.due_on)])
  if (item.job_name) facts.push(['Job', item.job_name])
  if (Number(item.amount) > 0) facts.push(['Amount', money(item.amount)])

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
            {TITLES[purpose]}
          </h2>
          <p className="mt-1 text-[0.8125rem] leading-5 text-ink-2">
            {purpose === 'dismiss'
              ? 'Close this because it is expected, and say why. It comes back only if the amount changes.'
              : 'Record what you have done, hand it to someone, or set a date to come back to it. This does not contact anyone or change the invoice or bill.'}
          </p>
        </div>

        <div className="rounded-lg bg-raised p-3">
          <Facts rows={facts} />
        </div>

        <label className="flex flex-col gap-2">
          <span className="text-[0.8125rem] text-ink-2">{purpose === 'dismiss' ? 'Why it is expected' : 'What you did'}</span>
          <textarea
            id="update-note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={3}
            autoFocus={purpose !== 'assign'}
            placeholder={
              purpose === 'dismiss'
                ? 'Timing. The rental bill posts next month'
                : 'Called their payables desk. Payment goes out Friday'
            }
            className="resize-none rounded-lg border border-hair bg-bg px-3 py-2 placeholder:text-muted"
          />
        </label>

        {purpose !== 'dismiss' && (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Select label="Owner" layout="stacked" value={owner} onChange={setOwner} options={owners} />
            <label className="flex min-w-0 flex-col gap-2">
              <span className="text-[0.8125rem] text-ink-2">Follow up on</span>
              <input type="date" value={followUp} onChange={(e) => setFollowUp(e.target.value)} className={FIELD} />
            </label>
          </div>
        )}

        {act.isError && <p className="text-[0.8125rem] text-neg">{act.error.message}</p>}

        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap justify-end gap-2">
            <Button onClick={() => dialog.current?.close()}>Cancel</Button>
            {purpose === 'dismiss' ? (
              <Button variant="primary" type="submit" disabled={!written || act.isPending}>
                {act.isPending ? 'Dismissing' : 'Dismiss'}
              </Button>
            ) : (
              <>
                <Button disabled={!written || act.isPending} onClick={() => save('resolve')}>
                  Save and resolve
                </Button>
                <Button variant="primary" type="submit" disabled={!changed || act.isPending}>
                  {act.isPending ? 'Saving' : 'Save'}
                </Button>
              </>
            )}
          </div>
          {purpose !== 'dismiss' && (
            <p className="text-right text-xs leading-4 text-muted">
              Saving keeps it open. Resolve it only once the problem itself is fixed, with a note saying how
            </p>
          )}
        </div>
      </form>
    </dialog>
  )
}
