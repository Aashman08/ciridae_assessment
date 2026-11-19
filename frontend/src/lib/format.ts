import type { Money } from './api'

const dollars = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })

/** One money format across the whole app: whole dollars, with a real minus sign. */
export function money(value: Money | number | null | undefined): string {
  if (value === null || value === undefined) return ''
  return dollars.format(Number(value)).replace('-', '−')
}

export function percent(value: string | null | undefined): string {
  return value === null || value === undefined ? '' : `${Number(value).toFixed(1)}%`.replace('-', '−')
}

function parse(isoDate: string): Date {
  // Dates from the API have no time. Reading them as UTC keeps the day from
  // shifting in time zones behind UTC.
  return new Date(`${isoDate.slice(0, 10)}T00:00:00Z`)
}

export function shortDate(isoDate: string | null | undefined): string {
  if (!isoDate) return 'Not yet'
  return parse(isoDate).toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' })
}

export function longDate(isoDate: string): string {
  return parse(isoDate).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' })
}

export function monthAndYear(isoDate: string): string {
  return parse(isoDate).toLocaleDateString('en-GB', { month: 'long', year: 'numeric', timeZone: 'UTC' })
}

export function dateTime(isoTimestamp: string): string {
  return new Date(isoTimestamp).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

export function daysBetween(laterIso: string, earlierIso: string): number {
  return Math.round((parse(laterIso).getTime() - parse(earlierIso).getTime()) / 86_400_000)
}

/** Source statuses arrive as SHOUTING_SNAKE_CASE. Show them as plain words. */
export function words(status: string | null | undefined): string {
  return (status ?? '').toLowerCase().replaceAll('_', ' ')
}

const STAGES: Record<string, string> = {
  WORK_NOT_STARTED: 'Not started',
  IN_PROGRESS: 'In progress',
  COMPLETED: 'Completed',
  CLOSED: 'Closed',
  CANCELLED: 'Cancelled',
}

export function stage(value: string): string {
  return STAGES[value] ?? words(value)
}

export function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? '' : 's'}`
}
