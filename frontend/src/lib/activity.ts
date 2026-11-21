import type { ActivitySource, CommitmentKind, CommitmentState } from './api'
import type { Tone } from './tones'

/** What happened, in a word or two. */
export const KINDS: Record<string, string> = {
  note: 'Note',
  opened: 'Found by a sync',
  assigned: 'Assigned',
  follow_up: 'Set a follow-up date',
  commented: 'Logged an update',
  suggested: 'Suggested by the assistant',
  resolved: 'Resolved',
  dismissed: 'Dismissed as expected',
  reopened: 'Reopened',
  cleared: 'Cleared by a sync',
  setting_changed: 'Changed a check',
  commitment_done: 'Marked a commitment done',
}

/** What an entry is, in a word or two. A note says which system it was written in. */
export function what(kind: string, source: ActivitySource): string {
  if (kind === 'note') return source === 'project' ? 'Project note' : 'Accounting note'
  return KINDS[kind] ?? kind
}

/** Who did it. A sync and the assistant are named as what they are. */
export function who(by: string): string {
  if (by === 'system') return 'A sync'
  if (by === 'assistant') return 'The assistant'
  return by
}

/** What kind of commitment, in a few words. */
export const COMMITMENT_KINDS: Record<CommitmentKind, string> = {
  payment_promised: 'Payment promised',
  promised_to_customer: 'Promised to the customer',
  waiting_on: 'Waiting on',
  we_will: 'Our next step',
}

/** Where a commitment stands, and the colour that says so. */
export const COMMITMENT_STATES: Record<CommitmentState, { label: string; tone: Tone }> = {
  missed: { label: 'Missed', tone: 'red' },
  due_soon: { label: 'Due soon', tone: 'amber' },
  open: { label: 'Open', tone: 'slate' },
  kept: { label: 'Kept', tone: 'green' },
  done: { label: 'Done', tone: 'green' },
}
