import type { UseQueryResult } from '@tanstack/react-query'
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { ApiError } from '../lib/api'
import { money } from '../lib/format'
import { buttonClass, cx } from '../lib/styles'
import { useRunSync } from '../lib/sync'

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <section className={cx('min-w-0 rounded-xl border border-hair bg-card shadow-lift', className)}>{children}</section>
}

/** A card's title row, with room on the right for one control. */
export function CardHead({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex min-h-14 flex-wrap items-center justify-between gap-x-4 gap-y-2 px-5 pt-3 pb-1">
      <h2 className="font-medium">{title}</h2>
      {children}
    </div>
  )
}

/** A number, what it counts, and what it compares to. Nothing decorative. */
export function Stat({ label, value, note }: { label: string; value: ReactNode; note: ReactNode }) {
  return (
    <Card className="flex flex-col gap-3 p-5">
      <span className="text-ink-2">{label}</span>
      <span className="text-[1.75rem] leading-7 font-medium tabular-nums">{value}</span>
      <span className="font-mono text-xs leading-4 text-muted">{note}</span>
    </Card>
  )
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'quiet' | 'primary'
}

export function Button({ variant = 'quiet', className, type = 'button', ...props }: ButtonProps) {
  return <button type={type} className={buttonClass(variant, className)} {...props} />
}

interface SegmentedProps<T extends string> {
  label: string
  value: T
  options: { value: T; label: string }[]
  onChange: (value: T) => void
}

export function Segmented<T extends string>({ label, value, options, onChange }: SegmentedProps<T>) {
  return (
    <div role="group" aria-label={label} className="inline-flex flex-wrap gap-0.5 rounded-[0.625rem] bg-raised p-1">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={option.value === value}
          onClick={() => onChange(option.value)}
          className={cx(
            'h-6 rounded-md px-2.5 text-[0.8125rem] transition-colors duration-150 ease-out',
            option.value === value ? 'bg-card text-ink shadow-lift ring-1 ring-hair' : 'text-ink-2 hover:text-ink',
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

interface PageHeadProps {
  title: string
  /** Shown beside the title in a quieter colour, e.g. how many rows there are. */
  aside?: ReactNode
  sub?: ReactNode
  children?: ReactNode
}

export function PageHead({ title, aside, sub, children }: PageHeadProps) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
      <div className="min-w-0">
        <h1 className="text-[1.75rem] leading-8 font-medium tracking-[-0.01em] md:text-[2rem] md:leading-9">
          {title}
          {aside !== undefined && <span className="text-muted"> {aside}</span>}
        </h1>
        {sub && <p className="mt-2 text-ink-2">{sub}</p>}
      </div>
      {children}
    </header>
  )
}

interface PagerProps {
  offset: number
  limit: number
  total: number
  onChange: (offset: number) => void
}

/** Shown only when there is more than one page. */
export function Pager({ offset, limit, total, onChange }: PagerProps) {
  if (total <= limit) return null
  const last = Math.min(offset + limit, total)
  return (
    <div className="flex items-center justify-between gap-4 border-t border-hair px-5 py-3">
      <span className="font-mono text-xs text-muted">
        {offset + 1} to {last} of {total}
      </span>
      <div className="flex gap-2">
        <Button disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>
          Previous
        </Button>
        <Button disabled={last >= total} onClick={() => onChange(offset + limit)}>
          Next
        </Button>
      </div>
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="px-5 py-8 text-muted">{children}</p>
}

/** Says what went wrong and what to do about it. */
export function ErrorNote({ error }: { error: unknown }) {
  const sync = useRunSync()
  const apiError = error instanceof ApiError ? error : null
  const neverSynced = apiError?.status === 409 && apiError.message.includes('No sync has finished')

  if (neverSynced) {
    return (
      <div className="flex flex-col items-start gap-3 px-5 py-8">
        <p className="font-medium">Nothing has been synced yet</p>
        <p className="max-w-prose text-ink-2">
          A sync reads Harborstone's CRM, project and accounting records and builds the job records shown here.
        </p>
        <Button variant="primary" disabled={sync.isPending} onClick={() => sync.mutate()}>
          {sync.isPending ? 'Syncing' : 'Run the first sync'}
        </Button>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-1 px-5 py-8">
      <p className="font-medium">This could not be loaded</p>
      <p className="max-w-prose text-ink-2">{error instanceof Error ? error.message : 'An unknown error occurred.'}</p>
      {apiError?.requestId && <p className="font-mono text-xs text-muted">Request {apiError.requestId}</p>}
    </div>
  )
}

interface LoadedProps<T> {
  query: UseQueryResult<T>
  children: (data: T) => ReactNode
}

/** Renders a query's data once it is there, and the loading or error state until then. */
export function Loaded<T>({ query, children }: LoadedProps<T>) {
  if (query.isPending) return <p className="px-5 py-8 text-muted">Loading</p>
  if (query.isError) return <ErrorNote error={query.error} />
  return <>{children(query.data)}</>
}

/** Figures are set in the mono face so digits line up; words stay in the text face. */
function isFigure(value: ReactNode): boolean {
  return typeof value === 'string' && /^[−$]?\d/.test(value)
}

/** A label and value pair list, with values right-aligned in one column. */
export function Facts({ rows }: { rows: [label: string, value: ReactNode, figure?: boolean][] }) {
  return (
    <dl className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-1 text-[0.8125rem]">
      {rows.map(([label, value, figure = isFigure(value)]) => (
        <div key={label} className="contents">
          <dt className="text-ink-2">{label}</dt>
          <dd className={cx('text-right', figure && 'font-mono text-xs leading-5 tabular-nums')}>{value}</dd>
        </div>
      ))}
    </dl>
  )
}

interface BarRowProps {
  label: string
  amount: number
  max: number
  tone?: 'outline' | 'solid' | 'accent'
}

/** One labelled bar with its dollar figure, drawn to a shared scale. */
export function BarRow({ label, amount, max, tone = 'solid' }: BarRowProps) {
  const width = max > 0 ? Math.max(0, (amount / max) * 100) : 0
  return (
    <div className="grid grid-cols-[6.5rem_minmax(0,1fr)_5.5rem] items-center gap-3 text-[0.8125rem] text-ink-2 sm:grid-cols-[9rem_minmax(0,1fr)_5.5rem]">
      <span>{label}</span>
      <span className="h-2 rounded bg-raised">
        <span
          className={cx(
            'block h-2 rounded',
            tone === 'outline' && 'ring-[1.5px] ring-muted ring-inset',
            tone === 'solid' && 'bg-ink-2',
            tone === 'accent' && 'bg-accent',
          )}
          style={{ width: `${width}%` }}
        />
      </span>
      <span className="text-right font-mono text-xs text-ink tabular-nums">
        {money(amount)}
      </span>
    </div>
  )
}
