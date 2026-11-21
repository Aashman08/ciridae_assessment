import type { UseQueryResult } from '@tanstack/react-query'
import { ArrowDown, ArrowUp, ArrowUpDown, Check, ChevronDown, Search } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Fragment, useEffect, useId, useRef, useState } from 'react'
import type { ButtonHTMLAttributes, CSSProperties, KeyboardEvent, ReactNode } from 'react'
import { ApiError } from '../lib/api'
import type { Order } from '../lib/api'
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
interface StatProps {
  label: string
  value: ReactNode
  note: ReactNode
  /** An icon for what the figure is about. Every stat card's icon is the same blue circle. */
  icon?: LucideIcon
}

export function Stat({ label, value, note, icon: Icon }: StatProps) {
  return (
    <Card className="flex flex-col gap-3 p-5">
      <span className="flex items-start justify-between gap-3">
        <span className="text-ink-2">{label}</span>
        {Icon && (
          <span aria-hidden className="grid size-9 shrink-0 place-items-center rounded-full bg-brand-soft text-brand-ink">
            <Icon size="1rem" strokeWidth={1.5} />
          </span>
        )}
      </span>
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

interface SortHeaderProps<Key extends string> {
  label: string
  /** The sort this column stands for. */
  by: Key
  /** The sort in force, and its direction. */
  sort: Key
  order: Order
  /** Which way a first click sorts. Money and counts start largest first; names and dates start at the top. */
  first?: Order
  onSort: (by: Key, order: Order) => void
  numeric?: boolean
  className?: string
}

/** A column heading that sorts the table. Click again to turn it round. */
export function SortHeader<Key extends string>({
  label,
  by,
  sort,
  order,
  first = 'desc',
  onSort,
  numeric = false,
  className,
}: SortHeaderProps<Key>) {
  const active = sort === by
  const next = active ? (order === 'asc' ? 'desc' : 'asc') : first
  const Arrow = active ? (order === 'asc' ? ArrowUp : ArrowDown) : ArrowUpDown
  return (
    <th className={cx(numeric && 'num', className)} aria-sort={active ? (order === 'asc' ? 'ascending' : 'descending') : undefined}>
      <button
        type="button"
        onClick={() => onSort(by, next)}
        className={cx(
          'group inline-flex items-center gap-1 rounded transition-colors duration-150 ease-out hover:text-ink',
          numeric && 'flex-row-reverse',
          active && 'text-ink',
        )}
      >
        {label}
        <Arrow
          size="0.75rem"
          strokeWidth={1.5}
          aria-hidden
          className={cx('shrink-0', !active && 'opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100')}
        />
      </button>
    </th>
  )
}

export interface SelectOption {
  value: string
  label: string
  /** Options with the same group are listed together under it. */
  group?: string
}

interface SelectProps {
  label: string
  value: string
  onChange: (value: string) => void
  /** When given, a first option standing for no filter. */
  all?: string
  options: SelectOption[]
  /** Width of the control. */
  className?: string
  /** The label sits beside the control in a row of filters, and above it in a form. */
  layout?: 'inline' | 'stacked'
  /** Keep the label for screen readers only, where a column heading already says it. */
  hideLabel?: boolean
}

/**
 * A dropdown drawn with the app's own parts, where a browser's built-in one
 * would bring the operating system's menu with it. Works with the keyboard:
 * arrows move, Enter or Space chooses, Escape closes.
 */
export function Select({ label, value, onChange, all, options, className = 'w-48', layout = 'inline', hideLabel = false }: SelectProps) {
  const id = useId()
  const button = useRef<HTMLButtonElement>(null)
  const list = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const [place, setPlace] = useState<CSSProperties>({})

  const choices: SelectOption[] = all === undefined ? options : [{ value: '', label: all }, ...options]
  const chosen = choices.find((choice) => choice.value === value)

  function show() {
    const box = button.current?.getBoundingClientRect()
    if (!box) return
    // The list is fixed to the window so nothing it sits inside can cut it off.
    // It opens downwards unless there is more room above.
    const below = window.innerHeight - box.bottom
    const upwards = below < 240 && box.top > below
    setPlace({
      left: box.left,
      minWidth: box.width,
      maxHeight: Math.max(120, (upwards ? box.top : below) - 16),
      ...(upwards ? { bottom: window.innerHeight - box.top + 4 } : { top: box.bottom + 4 }),
    })
    setActive(Math.max(0, choices.findIndex((choice) => choice.value === value)))
    setOpen(true)
  }

  function choose(index: number) {
    setOpen(false)
    if (choices[index] && choices[index].value !== value) onChange(choices[index].value)
  }

  useEffect(() => {
    if (!open) return
    const close = () => setOpen(false)
    function outside(event: MouseEvent) {
      const target = event.target as Node
      if (!button.current?.contains(target) && !list.current?.contains(target)) close()
    }
    function scrolled(event: Event) {
      // Scrolling the list itself is fine. Scrolling anything else would leave it stranded.
      if (!list.current?.contains(event.target as Node)) close()
    }
    document.addEventListener('mousedown', outside)
    window.addEventListener('resize', close)
    window.addEventListener('scroll', scrolled, true)
    return () => {
      document.removeEventListener('mousedown', outside)
      window.removeEventListener('resize', close)
      window.removeEventListener('scroll', scrolled, true)
    }
  }, [open])

  // Keep the option the keyboard is on in view.
  useEffect(() => {
    if (open) list.current?.querySelector('[data-active="true"]')?.scrollIntoView({ block: 'nearest' })
  }, [open, active])

  function keyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (!open) {
      if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(event.key)) {
        event.preventDefault()
        show()
      }
      return
    }
    const last = choices.length - 1
    const moves: Record<string, number> = {
      ArrowDown: Math.min(last, active + 1),
      ArrowUp: Math.max(0, active - 1),
      Home: 0,
      End: last,
    }
    if (event.key in moves) {
      event.preventDefault()
      setActive(moves[event.key])
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      choose(active)
    } else if (event.key === 'Escape') {
      // Close the list only. Inside a dialog, Escape must not also close the dialog.
      event.preventDefault()
      event.stopPropagation()
      setOpen(false)
    } else if (event.key === 'Tab') {
      setOpen(false)
    }
  }

  return (
    <div className={cx('flex min-w-0 text-[0.8125rem]', layout === 'inline' ? 'items-center gap-2' : 'flex-col gap-2')}>
      <span id={`${id}-label`} className={hideLabel ? 'sr-only' : 'text-ink-2'}>
        {label}
      </span>
      <button
        ref={button}
        type="button"
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={`${id}-list`}
        aria-labelledby={`${id}-label ${id}-value`}
        aria-activedescendant={open ? `${id}-${active}` : undefined}
        onClick={() => (open ? setOpen(false) : show())}
        onKeyDown={keyDown}
        className={cx(
          'grid grid-cols-[minmax(0,1fr)_1rem] items-center gap-2 rounded-lg border border-hair pr-2 pl-3 text-left text-ink',
          'transition-colors duration-150 ease-out hover:bg-raised',
          // In a row of filters it matches the other controls; in a form it matches the other fields.
          layout === 'inline' ? cx('h-8 bg-card', className) : 'h-9 w-full bg-bg text-[1rem]',
        )}
      >
        <span id={`${id}-value`} className="truncate">
          {chosen?.label ?? ''}
        </span>
        <ChevronDown size="1rem" strokeWidth={1.5} aria-hidden className="text-muted" />
      </button>

      {open && (
        <div
          ref={list}
          id={`${id}-list`}
          role="listbox"
          aria-labelledby={`${id}-label`}
          style={place}
          className="fixed z-50 flex flex-col gap-0.5 overflow-y-auto rounded-xl border border-hair bg-card p-1 text-[0.8125rem] shadow-float"
        >
          {choices.map((choice, index) => (
            <Fragment key={choice.value}>
              {choice.group && choice.group !== choices[index - 1]?.group && (
                <div className="px-2 pt-2 pb-1 text-xs leading-4 text-muted">{choice.group}</div>
              )}
              <div
                id={`${id}-${index}`}
                role="option"
                aria-selected={choice.value === value}
                data-active={index === active}
                onMouseEnter={() => setActive(index)}
                // Chosen on mouse down, before the button can lose focus and close the list.
                onMouseDown={(event) => {
                  event.preventDefault()
                  choose(index)
                }}
                className={cx(
                  'grid h-8 shrink-0 cursor-pointer grid-cols-[minmax(0,1fr)_1rem] items-center gap-3 rounded-lg px-2 whitespace-nowrap',
                  index === active && 'bg-raised',
                )}
              >
                {choice.label}
                {choice.value === value && <Check size="1rem" strokeWidth={1.5} aria-hidden />}
              </div>
            </Fragment>
          ))}
        </div>
      )}
    </div>
  )
}

/** A search box that reports what was typed once the typing pauses. */
export function SearchBox({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  const [text, setText] = useState(value)
  const [shown, setShown] = useState(value)
  // The address bar can change underneath the box, for example with the back button.
  if (value !== shown) {
    setShown(value)
    setText(value)
  }

  useEffect(() => {
    if (text.trim() === value) return
    const timer = setTimeout(() => onChange(text.trim()), 250)
    return () => clearTimeout(timer)
  }, [text, value, onChange])

  return (
    <label className="relative flex items-center">
      <span className="sr-only">{label}</span>
      <Search size="1rem" strokeWidth={1.5} aria-hidden className="pointer-events-none absolute left-2 text-muted" />
      <input
        type="search"
        value={text}
        onChange={(event) => setText(event.target.value)}
        placeholder={label}
        className="h-8 w-56 rounded-lg border border-hair bg-card pr-2 pl-8 text-[0.8125rem] placeholder:text-muted"
      />
    </label>
  )
}

interface ToggleProps {
  checked: boolean
  onChange: (checked: boolean) => void
  /** What the switch turns on, for anyone who cannot see it. */
  label: string
  disabled?: boolean
}

/** An on/off switch. */
export function Toggle({ checked, onChange, label, disabled }: ToggleProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cx(
        'inline-flex h-5 w-9 shrink-0 items-center rounded-full p-0.5 transition-colors duration-150 ease-out',
        checked ? 'bg-brand' : 'bg-raised ring-1 ring-hair ring-inset',
      )}
    >
      <span
        className={cx('size-4 rounded-full transition-transform duration-150 ease-out', checked ? 'translate-x-4 bg-card' : 'bg-muted')}
      />
    </button>
  )
}
