import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { JobTable } from '../components/JobTable'
import { Card, Loaded, PageHead, Pager, Segmented } from '../components/ui'
import { api } from '../lib/api'
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
  // Filters live in the address bar, so a filtered list can be bookmarked or sent to someone.
  const [params, setParams] = useSearchParams()
  const stage = params.get('stage') ?? ''
  const offset = Number(params.get('offset') ?? 0)

  const jobs = useQuery({
    queryKey: ['jobs', viewer.owner, stage, offset],
    queryFn: () => api.jobs({ owner: viewer.owner, stage, offset, limit: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  })

  function update(next: { stage?: string; offset?: number }) {
    const merged = { stage, offset, ...next }
    const search: Record<string, string> = {}
    if (merged.stage) search.stage = merged.stage
    if (merged.offset) search.offset = String(merged.offset)
    setParams(search)
  }

  return (
    <>
      <PageHead title="Jobs" aside={jobs.data?.total} sub="Open a job to compare its revenue and cost figures side by side">
        <Segmented label="Stage" value={stage} options={STAGES} onChange={(value) => update({ stage: value, offset: 0 })} />
      </PageHead>
      <Card>
        <Loaded query={jobs}>
          {(page) => (
            <>
              <JobTable jobs={page.data} full showOwner={!viewer.owner} />
              <Pager offset={offset} limit={PAGE_SIZE} total={page.total} onChange={(value) => update({ offset: value })} />
            </>
          )}
        </Loaded>
      </Card>
    </>
  )
}
