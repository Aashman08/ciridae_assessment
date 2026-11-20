import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { Button, Card, Loaded, PageHead } from '../components/ui'
import { api } from '../lib/api'
import type { IssueType } from '../lib/api'
import { money } from '../lib/format'
import { useRunSync } from '../lib/sync'

/** A tolerance is stored as a ratio (0.02) or as dollars (1). Show it the way people say it. */
function shown(type: IssueType): string {
  if (type.tolerance === null) return ''
  return type.tolerance_unit === 'ratio' ? `${Number(type.tolerance) * 100}%` : money(type.tolerance)
}

function ToleranceCell({ type }: { type: IssueType }) {
  const client = useQueryClient()
  const ratio = type.tolerance_unit === 'ratio'
  const [draft, setDraft] = useState<string | null>(null)

  const save = useMutation({
    mutationFn: (value: number) => api.updateIssueType(type.key, { tolerance: String(ratio ? value / 100 : value) }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ['issue-types'] })
      setDraft(null)
    },
  })

  // Most checks are yes or no and have nothing to tune.
  if (type.tolerance === null) return null

  if (draft === null) {
    return (
      <span className="flex items-center justify-end gap-3">
        <span className="font-mono text-[0.8125rem] tabular-nums">{shown(type)}</span>
        <Button onClick={() => setDraft(String(ratio ? Number(type.tolerance) * 100 : Number(type.tolerance)))}>Change</Button>
      </span>
    )
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    const value = Number(draft)
    if (draft !== '' && Number.isFinite(value) && value >= 0) save.mutate(value)
  }

  return (
    <form onSubmit={submit} className="flex items-center justify-end gap-2">
      <label className="flex items-center gap-1 text-[0.8125rem] text-ink-2">
        <span className="sr-only">Tolerance for {type.title}</span>
        {!ratio && '$'}
        <input
          id={`tolerance-${type.key}`}
          type="number"
          min="0"
          step="any"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          autoFocus
          className="h-8 w-16 rounded-lg border border-hair bg-bg px-2 text-right font-mono text-[0.8125rem] text-ink"
        />
        {ratio && '%'}
      </label>
      <Button type="submit" variant="primary" disabled={save.isPending}>
        Save
      </Button>
      <Button onClick={() => setDraft(null)}>Cancel</Button>
    </form>
  )
}

function Switch({ type }: { type: IssueType }) {
  const client = useQueryClient()
  const toggle = useMutation({
    mutationFn: () => api.updateIssueType(type.key, { enabled: !type.enabled }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['issue-types'] }),
  })

  return (
    <button
      type="button"
      role="switch"
      aria-checked={type.enabled}
      aria-label={`Check for ${type.title}`}
      disabled={toggle.isPending}
      onClick={() => toggle.mutate()}
      className={`inline-flex h-5 w-9 items-center rounded-full p-0.5 transition-colors duration-150 ease-out ${
        type.enabled ? 'bg-ink' : 'bg-raised ring-1 ring-hair ring-inset'
      }`}
    >
      <span
        className={`size-4 rounded-full transition-transform duration-150 ease-out ${
          type.enabled ? 'translate-x-4 bg-card' : 'bg-muted'
        }`}
      />
    </button>
  )
}

export function IssueTypes() {
  const types = useQuery({ queryKey: ['issue-types'], queryFn: api.issueTypes })
  const sync = useRunSync()

  return (
    <>
      <PageHead
        title="Issue types"
        aside={types.data?.length}
        sub="Each type is one way the three systems can disagree about a job. Changes take effect on the next sync"
      >
        {/* Syncs run on a schedule. This is for seeing the effect of a change straight away. */}
        <Button disabled={sync.isPending} onClick={() => sync.mutate()}>
          {sync.isPending ? 'Syncing' : 'Sync now'}
        </Button>
      </PageHead>
      <Card>
        <Loaded query={types}>
          {(data) => (
            <div className="overflow-x-auto">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Type</th>
                    <th>What it checks</th>
                    <th>Severity</th>
                    <th className="max-2xl:hidden">About</th>
                    <th className="num">Open</th>
                    <th className="num">Amount</th>
                    <th className="num">Tolerance</th>
                    <th>On</th>
                  </tr>
                </thead>
                <tbody>
                  {data.map((type) => (
                    <tr key={type.key}>
                      <td>
                        <Link to={`/issues?type=${type.key}`} className="font-medium hover:underline">
                          {type.title}
                        </Link>
                      </td>
                      <td className="min-w-56 py-2 text-[0.8125rem] text-ink-2 whitespace-normal!">
                        {type.description.replace(/\.$/, '')}
                      </td>
                      <td className="text-ink-2 capitalize">{type.severity}</td>
                      <td className="text-ink-2 capitalize max-2xl:hidden">{type.about}</td>
                      <td className="num">{type.open_count}</td>
                      <td className="num">{Number(type.open_amount) > 0 ? money(type.open_amount) : ''}</td>
                      <td className="text-right">
                        <ToleranceCell type={type} />
                      </td>
                      <td>
                        <Switch type={type} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Loaded>
      </Card>
    </>
  )
}
