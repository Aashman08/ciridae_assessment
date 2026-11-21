import { Calculator, CalendarClock, FileClock, FileQuestionMark, Flag, Gauge, HandCoins, Hourglass, Scale, Send, UserX } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { Item } from './api'

/**
 * Colour in this app means something, and the same thing everywhere:
 *   blue    customer money: invoices and billing
 *   violet  vendors: bills
 *   pink    cost
 *   teal    schedule: starting, finishing, keeping pace
 *   slate   ownership, and facts that are neither good nor bad
 *   red     late, failed or lost
 *   amber   waiting on someone
 *   green   saved, paid or done
 * Each is a soft fill with darker text of the same hue, from the tokens in index.css.
 */
export type Tone = 'blue' | 'violet' | 'green' | 'amber' | 'red' | 'pink' | 'teal' | 'slate'

/** The classes for a tinted chip or icon tile. Written out in full so Tailwind can find them. */
export const TONE: Record<Tone, string> = {
  blue: 'bg-tint-blue text-tint-blue-ink',
  violet: 'bg-tint-violet text-tint-violet-ink',
  green: 'bg-tint-green text-tint-green-ink',
  amber: 'bg-tint-amber text-tint-amber-ink',
  red: 'bg-tint-red text-tint-red-ink',
  pink: 'bg-tint-pink text-tint-pink-ink',
  teal: 'bg-tint-teal text-tint-teal-ink',
  slate: 'bg-tint-slate text-tint-slate-ink',
}

/**
 * What each kind of item is about. The colour says which part of the business (blue
 * customer money, violet vendors, pink cost, teal schedule, slate ownership); the icon
 * says which problem it is, so no two kinds look alike.
 */
export const KIND: Record<Item['kind'], { tone: Tone; icon: LucideIcon }> = {
  invoice_unpaid: { tone: 'blue', icon: HandCoins },
  invoice_not_sent: { tone: 'blue', icon: Send },
  billing_gap: { tone: 'blue', icon: Scale },
  bill_stuck: { tone: 'violet', icon: FileClock },
  bill_no_job: { tone: 'violet', icon: FileQuestionMark },
  cost_gap: { tone: 'pink', icon: Calculator },
  budget_risk: { tone: 'pink', icon: Gauge },
  late_start: { tone: 'teal', icon: CalendarClock },
  stalled: { tone: 'teal', icon: Hourglass },
  no_ops_manager: { tone: 'slate', icon: UserX },
  // Found by a check a person added.
  flagged: { tone: 'amber', icon: Flag },
}

/** The colour of one tag on an item, by what the tag says. */
export function tagTone(key: string): Tone {
  // A tag naming a kind of item, as on a job's row in the Issues list.
  if (key in KIND) return KIND[key as Item['kind']].tone
  switch (key) {
    case 'late':
    case 'posting_failed':
    case 'sync_failed':
    case 'urgent':
    case 'over_contract':
    case 'past_finish':
    case 'promise_missed':
      return 'red'
    case 'discount':
      return 'green'
    case 'needs_review':
    case 'pending_project_approval':
    case 'pending_finance_approval':
    case 'pending_corporate_review':
    case 'approved':
    case 'underbilled':
    case 'wait':
    case 'idle':
    case 'no_activity':
      return 'amber'
    case 'spent':
    case 'no_ledger_cost':
    case 'budget_burn':
      return 'pink'
    case 'closed_month':
      return 'violet'
    case 'waiting':
      return 'blue'
    default:
      return 'slate'
  }
}
