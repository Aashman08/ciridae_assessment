import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { ActivityTable } from '../components/ActivityTable'
import { Card, Loaded, PageHead, Pager, Select, Toggle } from '../components/ui'
import { KINDS } from '../lib/activity'
import { api } from '../lib/api'
import { useViewer } from '../lib/viewer'

const PAGE_SIZE = 50

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
            label="What"
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
              <ActivityTable
                entries={page.data}
                showJob
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
