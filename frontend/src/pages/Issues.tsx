import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { IssueTable } from '../components/IssueTable'
import { Card, Loaded, PageHead, Pager, Segmented, Select } from '../components/ui'
import { api } from '../lib/api'
import type { IssueSort, Order } from '../lib/api'
import { useViewer } from '../lib/viewer'

const PAGE_SIZE = 25

const STATUSES = [
  { value: 'active', label: 'Open' },
  { value: 'resolved', label: 'Resolved' },
]
const SEVERITIES = [
  { value: '', label: 'All' },
  { value: 'high', label: 'High' },
  { value: 'medium', label: 'Medium' },
]

interface Filters {
  type: string
  status: string
  severity: string
  owner: string
  sort: IssueSort
  order: Order
  offset: number
}

export function Issues() {
  const { viewer } = useViewer()
  // Filters, sorting and paging live in the address bar, so a list can be bookmarked or sent to someone.
  const [params, setParams] = useSearchParams()
  const filters: Filters = {
    type: params.get('type') ?? '',
    status: params.get('status') ?? 'active',
    severity: params.get('severity') ?? '',
    // Someone who only sees their own issues has no owner to choose.
    owner: viewer.owner ?? params.get('owner') ?? '',
    sort: (params.get('sort') ?? 'amount') as IssueSort,
    order: (params.get('order') ?? 'desc') as Order,
    offset: Number(params.get('offset') ?? 0),
  }

  const types = useQuery({ queryKey: ['issue-types'], queryFn: api.issueTypes })
  const people = useQuery({ queryKey: ['people'], queryFn: api.people, staleTime: Infinity })
  const issues = useQuery({
    queryKey: ['issues', filters],
    queryFn: () => api.issues({ ...filters, limit: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  })

  function update(next: Partial<Filters>) {
    // Changing a filter or the sort goes back to the first page.
    const merged = { ...filters, offset: 0, ...next }
    const search: Record<string, string> = {}
    if (merged.type) search.type = merged.type
    if (merged.status !== 'active') search.status = merged.status
    if (merged.severity) search.severity = merged.severity
    if (merged.owner && !viewer.owner) search.owner = merged.owner
    if (merged.sort !== 'amount' || merged.order !== 'desc') {
      search.sort = merged.sort
      search.order = merged.order
    }
    if (merged.offset) search.offset = String(merged.offset)
    setParams(search)
  }

  return (
    <>
      <PageHead title="Issues" aside={issues.data?.total} sub="One invoice or bill can appear under more than one type">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Segmented label="Status" value={filters.status} options={STATUSES} onChange={(status) => update({ status })} />
          <Segmented label="Severity" value={filters.severity} options={SEVERITIES} onChange={(severity) => update({ severity })} />
          <Select
            label="Type"
            value={filters.type}
            onChange={(type) => update({ type })}
            all="All types"
            options={(types.data ?? []).map((t) => ({ value: t.key, label: t.title }))}
            className="w-56"
          />
          {!viewer.owner && (
            <Select
              label="Owner"
              value={filters.owner}
              onChange={(owner) => update({ owner })}
              all="Everyone"
              options={(people.data ?? []).map((person) => ({ value: person.name, label: person.name }))}
              className="w-44"
            />
          )}
        </div>
      </PageHead>
      <Card>
        <Loaded query={issues}>
          {(page) => (
            <>
              <IssueTable
                issues={page.data}
                showOwner={!viewer.owner}
                showResolution={filters.status === 'resolved'}
                empty={filters.status === 'resolved' ? 'No resolved issues match these filters' : 'Nothing needs attention here'}
                sorting={{ sort: filters.sort, order: filters.order, onSort: (sort, order) => update({ sort, order }) }}
              />
              <Pager offset={filters.offset} limit={PAGE_SIZE} total={page.total} onChange={(offset) => update({ offset })} />
            </>
          )}
        </Loaded>
      </Card>
    </>
  )
}
