import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ChevronRight } from 'lucide-react'
import { Fragment } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ItemTable, Tags } from '../components/ItemTable'
import { Card, Empty, Loaded, PageHead, Segmented, Select } from '../components/ui'
import { api } from '../lib/api'
import type { JobItems } from '../lib/api'
import { money } from '../lib/format'
import { cx } from '../lib/styles'
import { useViewer } from '../lib/viewer'

const STATES = [
  { value: 'needs_action', label: 'Needs action' },
  { value: 'waiting', label: 'Waiting' },
  { value: 'done', label: 'Done' },
]

const ICON = { size: '1rem', strokeWidth: 1.5, 'aria-hidden': true } as const

// What a group is called in the address bar. Bills with no job have no job number.
const NO_JOB = 'no-job'
const name = (group: JobItems) => group.job_number ?? NO_JOB

/**
 * What needs fixing, one row per job. A row says what is wrong on the job and
 * how much is flagged; opening it lists each thing to fix, with its next step.
 * Vendor bills that are on no job come first, in a group of their own.
 */
export function Issues() {
  const { viewer } = useViewer()
  // Filters and which job is open live in the address bar, so a view can be bookmarked or sent to someone.
  const [params, setParams] = useSearchParams()
  const state = params.get('state') ?? 'needs_action'
  const type = params.get('type') ?? ''
  // Someone who only sees their own work has no owner to choose.
  const owner = viewer.owner ?? params.get('owner') ?? ''
  const open = params.get('open')

  const types = useQuery({ queryKey: ['issue-types'], queryFn: api.issueTypes })
  const people = useQuery({ queryKey: ['people'], queryFn: api.people, staleTime: Infinity })
  const items = useQuery({
    queryKey: ['items', state, owner, type],
    queryFn: () => api.items({ state, owner, type }),
    placeholderData: keepPreviousData,
  })

  function update(next: { state?: string; type?: string; owner?: string; open?: string | null }) {
    const merged = { state, type, owner, open, ...next }
    const search: Record<string, string> = {}
    if (merged.state !== 'needs_action') search.state = merged.state
    if (merged.type) search.type = merged.type
    if (merged.owner && !viewer.owner) search.owner = merged.owner
    if (merged.open) search.open = merged.open
    setParams(search)
  }

  return (
    <>
      <PageHead
        title="Issues"
        aside={items.data?.item_count}
        sub="One row per job. Open a job to see each thing to fix on it and start the next step"
      >
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Segmented label="State" value={state} options={STATES} onChange={(value) => update({ state: value, open: null })} />
          <Select
            label="Check"
            value={type}
            onChange={(value) => update({ type: value, open: null })}
            all="All checks"
            options={(types.data ?? []).map((t) => ({ value: t.key, label: t.title }))}
            className="w-56"
          />
          {!viewer.owner && (
            <Select
              label="Owner"
              value={owner}
              onChange={(value) => update({ owner: value, open: null })}
              all="Everyone"
              options={(people.data ?? []).map((person) => ({ value: person.name, label: person.name }))}
              className="w-44"
            />
          )}
        </div>
      </PageHead>

      <Card>
        <Loaded query={items}>
          {({ groups }) =>
            groups.length === 0 ? (
              <Empty>
                {state === 'needs_action'
                  ? 'Nothing needs action here'
                  : state === 'waiting'
                    ? 'Nothing is waiting on a date'
                    : 'Nothing has been closed yet'}
              </Empty>
            ) : (
              <div className="relative overflow-x-auto">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th className="w-10">
                        <span className="sr-only">Open</span>
                      </th>
                      <th>Job ID</th>
                      <th>Job</th>
                      {!viewer.owner && <th className="max-md:hidden">Ops manager</th>}
                      <th className="max-md:hidden">What is wrong</th>
                      <th className="num">To fix</th>
                      <th className="num">Flagged</th>
                    </tr>
                  </thead>
                  <tbody>
                    {groups.map((group) => {
                      const expanded = open === name(group)
                      return (
                        <Fragment key={name(group)}>
                          <tr
                            className="clickable"
                            aria-expanded={expanded}
                            onClick={() => update({ open: expanded ? null : name(group) })}
                          >
                            <td className="pr-0!">
                              <ChevronRight
                                {...ICON}
                                className={cx('text-muted transition-transform duration-150 ease-out', expanded && 'rotate-90')}
                              />
                            </td>
                            <td className="font-mono text-[0.8125rem] text-ink-2">{group.job_number ?? ''}</td>
                            <td>
                              {group.job_number ? (
                                // The name goes to the job's page; anywhere else on the row opens its items here.
                                <Link
                                  to={`/jobs/${group.job_number}`}
                                  className="block max-w-[17rem] truncate font-medium hover:underline 2xl:max-w-[28rem]"
                                  title={group.job_name ?? undefined}
                                  onClick={(event) => event.stopPropagation()}
                                >
                                  {group.job_name}
                                </Link>
                              ) : (
                                <span className="font-medium">Vendor bills on no job</span>
                              )}
                            </td>
                            {!viewer.owner && (
                              <td className={cx('max-md:hidden', group.ops_manager || !group.job_number ? 'text-ink-2' : 'text-accent-ink')}>
                                {group.job_number ? (group.ops_manager ?? 'None assigned') : ''}
                              </td>
                            )}
                            <td className="min-w-[15rem] max-md:hidden">
                              <Tags tags={group.tags} />
                            </td>
                            <td className="num">{group.items.length}</td>
                            <td className="num">{Number(group.flagged_amount) > 0 ? money(group.flagged_amount) : ''}</td>
                          </tr>
                          {expanded && (
                            <tr>
                              <td colSpan={viewer.owner ? 6 : 7} className="h-auto! bg-card p-3! md:p-4!">
                                <div className="overflow-hidden rounded-lg border border-hair bg-card">
                                  <ItemTable items={group.items} />
                                </div>
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )
          }
        </Loaded>
      </Card>
    </>
  )
}
