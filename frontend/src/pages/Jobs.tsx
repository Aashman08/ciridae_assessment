import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { JobTable } from '../components/JobTable'
import { Card, Loaded, PageHead, Pager, SearchBox, Segmented } from '../components/ui'
import { api } from '../lib/api'
import type { JobSort, Order } from '../lib/api'
import { useViewer } from '../lib/viewer'

const PAGE_SIZE = 25

const STAGES = [
  { value: '', label: 'All' },
  { value: 'IN_PROGRESS', label: 'In progress' },
  { value: 'COMPLETED', label: 'Completed' },
  { value: 'CLOSED', label: 'Closed' },
  { value: 'WORK_NOT_STARTED', label: 'Not started' },
]

export function Jobs() {
  const { viewer } = useViewer()
  // Filters, sorting and paging live in the address bar, so a list can be bookmarked or sent to someone.
  const [params, setParams] = useSearchParams()
  const stage = params.get('stage') ?? ''
  const q = params.get('q') ?? ''
  const sort = (params.get('sort') ?? 'issues') as JobSort
  const order = (params.get('order') ?? 'desc') as Order
  const offset = Number(params.get('offset') ?? 0)

  const jobs = useQuery({
    queryKey: ['jobs', viewer.owner, stage, q, sort, order, offset],
    queryFn: () => api.jobs({ owner: viewer.owner, stage, q, sort, order, offset, limit: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  })

  function update(next: { stage?: string; q?: string; sort?: JobSort; order?: Order; offset?: number }) {
    const merged = { stage, q, sort, order, offset, ...next }
    const search: Record<string, string> = {}
    if (merged.stage) search.stage = merged.stage
    if (merged.q) search.q = merged.q
    if (merged.sort !== 'issues' || merged.order !== 'desc') {
      search.sort = merged.sort
      search.order = merged.order
    }
    if (merged.offset) search.offset = String(merged.offset)
    setParams(search)
  }

  // The search box reports after a pause; it needs a function that does not change under it.
  const search = useCallback(
    (value: string) => {
      setParams((current) => {
        const next = new URLSearchParams(current)
        if (value) next.set('q', value)
        else next.delete('q')
        next.delete('offset')
        return next
      })
    },
    [setParams],
  )

  return (
    <>
      <PageHead
        title="Jobs"
        aside={jobs.data?.total}
        sub="Revenue, cost and profit are the ledger's. Open a job for its other figures"
      >
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <SearchBox label="Job, number or customer" value={q} onChange={search} />
          <Segmented label="Stage" value={stage} options={STAGES} onChange={(value) => update({ stage: value, offset: 0 })} />
        </div>
      </PageHead>
      <Card>
        <Loaded query={jobs}>
          {(page) => (
            <>
              <JobTable
                jobs={page.data}
                full
                showOwner={!viewer.owner}
                sorting={{ sort, order, onSort: (by, direction) => update({ sort: by, order: direction, offset: 0 }) }}
              />
              <Pager offset={offset} limit={PAGE_SIZE} total={page.total} onChange={(value) => update({ offset: value })} />
            </>
          )}
        </Loaded>
      </Card>
    </>
  )
}
