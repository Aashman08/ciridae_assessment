import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { useAssistant } from '../lib/assistant'
import type { ActivityEntry } from '../lib/api'
import { dateTime } from '../lib/format'
import { who } from '../lib/activity'
import { Card, Empty, Loaded, PageHead, Pager, Select, Toggle } from '../components/ui'
import { KINDS } from '../lib/activity'
import { api } from '../lib/api'
import { useViewer } from '../lib/viewer'

const PAGE_SIZE = 50

/**
 * The log itself: who did what, to what, and when, one line each. Everything else about
 * an entry (what it changed, the note in full) opens in the side pane.
 */
function AuditTable({ entries, empty }: { entries: ActivityEntry[]; empty: string }) {
  const { view, show } = useAssistant()
  const open = view?.kind === 'audit' ? view.entry.ref : null
  if (entries.length === 0) return <Empty>{empty}</Empty>
  return (
    <div className="min-w-0 overflow-x-auto">
      <table className="data-table">
        <thead>
          <tr>
            <th>When</th>
            <th>Who</th>
            <th>Action</th>
            <th>Record</th>
            <th className="max-md:hidden">Job</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <tr
              key={entry.ref}
              className={`clickable ${open === entry.ref ? 'bg-brand-soft/50' : ''}`}
              onClick={() => show({ kind: 'audit', entry })}
            >
              <td className="text-ink-2">{dateTime(entry.at)}</td>
              <td>{who(entry.by)}</td>
              <td className="font-medium">{entry.action}</td>
              <td className={entry.document || entry.job_number === entry.record ? 'font-mono text-[0.8125rem]' : ''}>{entry.record ?? ''}</td>
              <td className="max-w-[18rem] truncate text-ink-2 max-md:hidden">{entry.job_name ?? ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/**
 * The audit log: everything anyone did in this app, newest first, and nothing else.
 * Notes written in the source systems are not actions; they are on each job's page.
 * Read-only. Filters and paging
 * live in the address, so a filtered log can be bookmarked or sent to someone.
 */
export function Activity() {
  const { viewer } = useViewer()
  const [params, setParams] = useSearchParams()
  const person = params.get('person') ?? ''
  const kind = params.get('kind') ?? ''
  const job = params.get('job') ?? ''
  const offset = Number(params.get('offset') ?? 0)
  // What syncs did is most of the log, so it is left out until someone asks for it.
  const syncs = params.get('syncs') === '1'

  function update(next: { person?: string; kind?: string; job?: string; syncs?: string; offset?: number }) {
    const merged = { person, kind, job, syncs: syncs ? '1' : '', offset, ...next }
    const search: Record<string, string> = {}
    for (const [key, value] of Object.entries(merged)) if (value) search[key] = String(value)
    setParams(search)
  }

  const people = useQuery({ queryKey: ['people'], queryFn: api.people })
  const jobs = useQuery({ queryKey: ['jobs', 'all', viewer.owner], queryFn: () => api.jobs({ owner: viewer.owner, limit: 200 }) })
  const log = useQuery({
    queryKey: ['activity', 'log', viewer.owner, person, kind, job, syncs, offset],
    queryFn: () =>
      api.activity({ owner: viewer.owner, source: 'app', person, kind, job, people_only: !syncs && person !== 'system', offset, limit: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  })

  return (
    <>
      <PageHead
        title="Audit log"
        aside={log.data?.total}
        sub="Everything anyone did in this app, newest first"
      >
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Select
            label="Who"
            value={person}
            onChange={(value) => update({ person: value, offset: 0 })}
            all="Everyone"
            options={[
              ...(people.data ?? []).map((p) => ({ value: p.name, label: p.name })),
              { value: 'system', label: 'A sync' },
              { value: 'assistant', label: 'The assistant' },
            ]}
            className="w-48"
          />
          <Select
            label="Action"
            value={kind}
            onChange={(value) => update({ kind: value, offset: 0 })}
            all="Anything"
            options={Object.entries(KINDS)
              .filter(([value]) => value !== 'note')
              .map(([value, label]) => ({ value, label }))}
            className="w-48"
          />
          <Select
            label="Job"
            value={job}
            onChange={(value) => update({ job: value, offset: 0 })}
            all="All jobs"
            options={(jobs.data?.data ?? []).map((j) => ({ value: j.job_number, label: j.name }))}
            className="w-64"
          />
          <label className="flex items-center gap-2 text-[0.8125rem] text-ink-2">
            <Toggle checked={syncs} onChange={(value) => update({ syncs: value ? '1' : '', offset: 0 })} label="Show what syncs did" />
            Show what syncs did
          </label>

        </div>
      </PageHead>
      <Card>
        <Loaded query={log}>
          {(page) => (
            <>
              <AuditTable
                entries={page.data}
                empty={person || kind || job ? 'Nothing matches these filters' : 'Nobody has done anything yet'}
              />
              <Pager offset={offset} limit={PAGE_SIZE} total={page.total} onChange={(value) => update({ offset: value })} />
            </>
          )}
        </Loaded>
      </Card>
    </>
  )
}
