import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Check,
  ChevronRight,
  ChevronsUpDown,
  FileText,
  HardHat,
  LayoutDashboard,
  ListChecks,
  MessageCircleQuestion,
  Moon,
  Plug,
  Receipt,
  TriangleAlert,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import { useAssistant } from '../lib/assistant'
import { dateTime, longDate } from '../lib/format'
import { cx } from '../lib/styles'
import { useLatestSync } from '../lib/sync'
import { useTheme } from '../lib/theme'
import { useViewer, VIEWERS } from '../lib/viewer'
import { AssistantPane } from './AssistantPane'
import { Button, Toggle } from './ui'

interface Section {
  to: string
  label: string
  icon: LucideIcon
  /** Only for people who can change how issues are detected. */
  managesChecks?: boolean
}

const CONNECTORS: Section = { to: '/connectors', label: 'Connectors', icon: Plug }

const SECTIONS: Section[] = [
  { to: '/', label: 'Overview', icon: LayoutDashboard },
  { to: '/ask', label: 'Ask', icon: MessageCircleQuestion },
  { to: '/jobs', label: 'Jobs', icon: HardHat },
  { to: '/issues', label: 'Issues', icon: TriangleAlert },
  { to: '/invoices', label: 'Customer invoices', icon: Receipt },
  { to: '/bills', label: 'Vendor bills', icon: FileText },
  { to: '/issue-types', label: 'Issue types', icon: ListChecks, managesChecks: true },
]

// One icon size and stroke everywhere, in the colour of the text around it.
const ICON = { size: '1rem', strokeWidth: 1.5, 'aria-hidden': true } as const

const ROW =
  'grid h-9 shrink-0 grid-cols-[1rem_minmax(0,1fr)_auto] items-center gap-2 rounded-lg px-2 text-left text-ink-2 ' +
  'transition-colors duration-150 ease-out hover:bg-side-hover hover:text-ink'
// The frame is white; the page you are on is the one darker row in it.
const ROW_ACTIVE = 'bg-side-active font-medium text-ink hover:bg-side-active'

function Mark() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true" className="size-5 shrink-0">
      <rect x="2" y="2" width="16" height="16" rx="4" className="fill-ink" />
      <path
        d="M6 10.5l2.5 2.5L14 7.5"
        fill="none"
        className="stroke-accent"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function Initial({ name }: { name: string }) {
  return (
    <span className="size-6 shrink-0 rounded-md bg-raised text-center text-xs leading-6 text-ink-2 ring-1 ring-hair ring-inset">
      {name[0]}
    </span>
  )
}

/**
 * Who is signed in. It sits above the navigation because it decides what every
 * page below it shows; choosing someone else is like signing in as them.
 */
function AccountSwitcher() {
  const { viewer, setViewer } = useViewer()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function close(event: MouseEvent | KeyboardEvent) {
      const escape = event instanceof KeyboardEvent && event.key === 'Escape'
      const outside = event instanceof MouseEvent && !box.current?.contains(event.target as Node)
      if (escape || outside) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', close)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', close)
    }
  }, [open])

  return (
    <div ref={box} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="grid w-full grid-cols-[1.5rem_minmax(0,1fr)_1rem] items-center gap-2 rounded-lg bg-side p-2 text-left ring-1 ring-hair ring-inset transition-colors duration-150 ease-out hover:bg-side-hover"
      >
        <Initial name={viewer.name} />
        <span className="min-w-0">
          <span className="block truncate font-medium">{viewer.name}</span>
          <span className="block truncate text-xs leading-4 text-muted">{viewer.sees}</span>
        </span>
        <ChevronsUpDown {...ICON} className="text-muted" />
      </button>

      {open && (
        <div
          role="menu"
          aria-label="Sign in as"
          className="absolute inset-x-0 top-full z-10 mt-1 flex flex-col gap-0.5 rounded-xl border border-hair bg-card p-1 shadow-float"
        >
          {VIEWERS.map((person) => (
            <button
              key={person.key}
              type="button"
              role="menuitemradio"
              aria-checked={person.key === viewer.key}
              onClick={() => {
                setViewer(person)
                setOpen(false)
                // Everything on screen belongs to the previous person, so start again from the top.
                navigate('/')
              }}
              className="grid grid-cols-[1.5rem_minmax(0,1fr)_1rem] items-center gap-2 rounded-lg p-2 text-left transition-colors duration-150 ease-out hover:bg-raised"
            >
              <Initial name={person.name} />
              <span className="min-w-0">
                <span className="block truncate">{person.name}</span>
                <span className="block truncate text-xs leading-4 text-muted">{person.sees}</span>
              </span>
              {person.key === viewer.key && <Check {...ICON} />}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function Sidebar() {
  const { viewer } = useViewer()
  const [theme, setTheme] = useTheme()
  const summary = useQuery({ queryKey: ['summary', viewer.owner], queryFn: () => api.summary(viewer.owner) })
  const counts: Record<string, number | undefined> = {
    '/jobs': summary.data?.job_count,
    '/issues': summary.data?.open_item_count,
    '/invoices': summary.data?.cash.invoice_count,
    '/bills': summary.data?.cash.vendor_bills_count,
  }
  const sections = SECTIONS.filter((section) => viewer.managesChecks || !section.managesChecks)

  return (
    <aside className="flex flex-col border-b border-hair bg-side px-4 py-3 md:sticky md:top-0 md:h-screen md:overflow-y-auto md:border-r md:border-b-0 md:px-3 md:py-4">
      {/* On a wide screen the name sits in a row as tall as the top bar, with the same line under it,
          so the bar and the sidebar meet in one straight line. */}
      <Link
        to="/"
        className="flex h-9 shrink-0 items-center gap-2 px-2 text-base font-semibold md:-mx-3 md:-mt-4 md:h-14 md:border-b md:border-hair md:px-5"
      >
        <Mark />
        Reconciliation
      </Link>

      <p className="hidden px-2 pt-5 pb-2 text-xs leading-4 text-muted md:block">Signed in as</p>
      <div className="pt-2 md:pt-0">
        <AccountSwitcher />
      </div>

      {/* The heading says exactly what the pages under it cover, so the scope is never a surprise. */}
      <p className="hidden px-2 pt-6 pb-2 text-xs leading-4 text-muted md:block">{viewer.scope}</p>
      <nav aria-label={viewer.scope} className="flex gap-1 overflow-x-auto pt-2 md:flex-col md:gap-0.5 md:overflow-visible md:pt-0">
        {sections.map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => `${ROW} ${isActive ? ROW_ACTIVE : ''}`}>
            {({ isActive }) => (
              <>
                <Icon {...ICON} className={isActive ? 'text-brand' : 'text-muted'} />
                <span className="truncate">{label}</span>
                <span className="font-mono text-xs text-muted tabular-nums">{counts[to] ?? ''}</span>
              </>
            )}
          </NavLink>
        ))}
      </nav>

      {/* Settings sit at the bottom, in the same rows as the pages above them. */}
      <div className="mt-auto flex gap-1 pt-3 md:flex-col md:gap-0.5 md:pt-6">
        <NavLink to="/connectors" className={({ isActive }) => `${ROW} ${isActive ? ROW_ACTIVE : ''}`}>
          {({ isActive }) => (
            <>
              <Plug {...ICON} className={isActive ? 'text-brand' : 'text-muted'} />
              <span className="truncate">Connectors</span>
              <span />
            </>
          )}
        </NavLink>
        <label className={`${ROW} cursor-pointer`}>
          <Moon {...ICON} className="text-muted" />
          <span className="truncate">Dark mode</span>
          <Toggle checked={theme === 'dark'} onChange={(dark) => setTheme(dark ? 'dark' : 'light')} label="Dark mode" />
        </label>
      </div>
    </aside>
  )
}

function Crumb() {
  const { pathname } = useLocation()
  const [, first, second] = pathname.split('/')
  const section = [...SECTIONS, CONNECTORS].find((s) => s.to === `/${first}`) ?? SECTIONS[0]
  const Icon = section.icon
  return (
    <div className="flex min-w-0 items-center gap-2 text-ink-2">
      <Icon {...ICON} />
      {second ? (
        <>
          <Link to={section.to} className="transition-colors duration-150 hover:text-ink">
            {section.label}
          </Link>
          <ChevronRight {...ICON} />
          <span className="truncate font-mono text-[0.8125rem] font-medium text-ink">{second}</span>
        </>
      ) : (
        <span className="font-medium text-ink">{section.label}</span>
      )}
    </div>
  )
}

/** When the figures are from, and the way into the assistant from any page. */
function TopBarRight() {
  const client = useQueryClient()
  const latest = useLatestSync()
  const { view, show, close } = useAssistant()
  const { pathname } = useLocation()
  const run = latest.data

  // Syncs run on a schedule. When a new one lands, everything on screen is out of date.
  const seen = useRef<number | null>(null)
  useEffect(() => {
    if (!run) return
    if (seen.current !== null && seen.current !== run.id) void client.invalidateQueries()
    seen.current = run.id
  }, [run, client])

  const chatting = view?.kind === 'chat'
  return (
    <div className="flex items-center gap-4">
      {run && (
        <p className="hidden text-right text-xs leading-4 text-muted lg:block">
          Figures as of {longDate(run.as_of)}
          <br />
          Last synced {dateTime(run.finished_at ?? run.started_at)}
        </p>
      )}
      {/* The Ask page is the assistant already. */}
      {pathname !== '/ask' && (
        <Button aria-pressed={chatting} onClick={() => (chatting ? close() : show({ kind: 'chat' }))}>
          <MessageCircleQuestion {...ICON} />
          Ask AI
        </Button>
      )}
    </div>
  )
}

export function Shell() {
  const { pathname } = useLocation()
  const { view } = useAssistant()
  return (
    // The assistant's pane takes a third column on a wide screen and slides over the page on a narrower one,
    // where a third column would squeeze the page until its tables no longer fit.
    <div
      className={cx(
        'grid min-h-full grid-cols-1',
        !view
          ? 'md:grid-cols-[15.5rem_minmax(0,1fr)]'
          : view.kind === 'document'
            ? // An invoice or bill reads like a page, so it gets a wider pane than a chat or a draft.
              'md:grid-cols-[15.5rem_minmax(0,1fr)] 2xl:grid-cols-[15.5rem_minmax(0,1fr)_38rem]'
            : 'md:grid-cols-[15.5rem_minmax(0,1fr)] 2xl:grid-cols-[15.5rem_minmax(0,1fr)_26rem]',
      )}
    >
      <Sidebar />
      <div className="flex min-w-0 flex-col">
        {/* The top bar is part of the frame, with the sidebar, so it shares the sidebar's white. */}
        <header className="sticky top-0 z-20 flex h-14 items-center justify-between gap-4 border-b border-hair bg-side px-4 md:px-6">
          <Crumb />
          <TopBarRight />
        </header>
        {/* Keyed on the path so the short entrance plays once per page, not on every refetch. */}
        <main key={pathname} className="@container flex w-full animate-rise flex-col gap-6 px-4 pt-6 pb-12 md:px-6 md:pt-8 md:pb-16 2xl:px-8">
          <Outlet />
        </main>
      </div>
      <AssistantPane />
    </div>
  )
}
