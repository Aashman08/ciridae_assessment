import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { IssueTable } from '../components/IssueTable'
import { Card, Loaded, PageHead, Pager, Segmented } from '../components/ui'
import { api } from '../lib/api'
import { useViewer } from '../lib/viewer'

const PAGE_SIZE = 25

const STATUSES = [
  { value: 'active', label: 'Open' },
  { value: 'resolved', label: 'Resolved' },
]

export function Issues() {
  const { viewer } = useViewer()
  const [params, setParams] = useSearchParams()
  const type = params.get('type') ?? ''
  const status = params.get('status') ?? 'active'
  const offset = Number(params.get('offset') ?? 0)

  const types = useQuery({ queryKey: ['issue-types'], queryFn: api.issueTypes })
  const issues = useQuery({
    queryKey: ['issues', viewer.owner, type, status, offset],
    queryFn: () => api.issues({ owner: viewer.owner, type, status, offset, limit: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  })

  function update(next: { type?: string; status?: string; offset?: number }) {
    const merged = { type, status, offset, ...next }
    const search: Record<string, string> = {}
    if (merged.type) search.type = merged.type
    if (merged.status !== 'active') search.status = merged.status
    if (merged.offset) search.offset = String(merged.offset)
    setParams(search)
  }

  return (
    <>
      <PageHead title="Issues" aside={issues.data?.total} sub="One invoice or bill can appear under more than one type">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Segmented label="Status" value={status} options={STATUSES} onChange={(value) => update({ status: value, offset: 0 })} />
          <label className="flex items-center gap-2 text-[0.8125rem] text-ink-2">
            Type
            <select
              id="issue-type-filter"
              value={type}
              onChange={(e) => update({ type: e.target.value, offset: 0 })}
              className="h-8 w-60 rounded-lg border border-hair bg-card px-2 text-ink"
            >
              <option value="">All types</option>
              {types.data?.map((t) => (
                <option key={t.key} value={t.key}>
                  {t.title}
                </option>
              ))}
            </select>
          </label>
        </div>
      </PageHead>
      <Card>
        <Loaded query={issues}>
          {(page) => (
            <>
              <IssueTable
                issues={page.data}
                showOwner={!viewer.owner}
                showResolution={status === 'resolved'}
                empty={status === 'resolved' ? 'No issues have been resolved yet' : 'Nothing needs attention here'}
              />
              <Pager offset={offset} limit={PAGE_SIZE} total={page.total} onChange={(value) => update({ offset: value })} />
            </>
          )}
        </Loaded>
      </Card>
    </>
  )
}
