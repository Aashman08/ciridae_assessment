import type { ActivitySource, CommitmentKind, CommitmentState } from './api'
import type { Tone } from './tones'

/** What happened, in a word or two. */
export const KINDS: Record<string, string> = {
  note: 'Note',
  opened: 'Found',
  assigned: 'Assigned',
  follow_up: 'Follow-up set',
  commented: 'Update logged',
  suggested: 'Suggestion',
  resolved: 'Resolved',
  dismissed: 'Dismissed',
  reopened: 'Reopened',
  cleared: 'Cleared',
  setting_changed: 'Check changed',
  commitment_done: 'Commitment done',
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
