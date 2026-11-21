import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { Pencil } from 'lucide-react'
import { Link } from 'react-router-dom'
import { AddCheck } from '../components/AddCheck'
import { Button, Card, Loaded, PageHead, Select, Toggle } from '../components/ui'
import { api } from '../lib/api'
import type { IssueType } from '../lib/api'
import { money } from '../lib/format'
import { useViewer } from '../lib/viewer'

/** A tolerance is stored as a ratio (0.02), as days (14) or as dollars (1). Show it the way people say it. */
function shown(type: IssueType): string {
  if (type.tolerance === null) return ''
  if (type.tolerance_unit === 'ratio') return `${Number(type.tolerance) * 100}%`
  if (type.tolerance_unit === 'days') return `${Number(type.tolerance)} days`
  return money(type.tolerance)
}

function ToleranceCell({ type }: { type: IssueType }) {
  const { viewer } = useViewer()
  const client = useQueryClient()
  const ratio = type.tolerance_unit === 'ratio'
  const [draft, setDraft] = useState<string | null>(null)

  const save = useMutation({
    mutationFn: (value: number) => api.updateIssueType(type.key, { tolerance: String(ratio ? value / 100 : value), actor: viewer.name }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ['issue-types'] })
      setDraft(null)
    },
  })

  // Most checks are yes or no and have nothing to tune.
  if (type.tolerance === null) return null

  if (draft === null) {
    return (
      // The value is the button: click it to change it.
      <Button
        aria-label={`Change the tolerance for ${type.title}, now ${shown(type)}`}
        className="font-mono tabular-nums"
        onClick={() => setDraft(String(ratio ? Number(type.tolerance) * 100 : Number(type.tolerance)))}
      >
        {shown(type)}
      </Button>
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

/** How serious a check's findings are: the business decides, so it can be changed here. */
function SeverityCell({ type }: { type: IssueType }) {
  const { viewer } = useViewer()
  const client = useQueryClient()
  const change = useMutation({
    mutationFn: (severity: 'high' | 'medium') => api.updateIssueType(type.key, { severity, actor: viewer.name }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['issue-types'] }),
  })
  return (
    <Select
      label={`Severity of ${type.title}`}
      value={type.severity}
      onChange={(value) => change.mutate(value as 'high' | 'medium')}
      options={[
        { value: 'high', label: 'High' },
        { value: 'medium', label: 'Medium' },
      ]}
      className="w-[6.5rem]"
      hideLabel
    />
  )
}

function Switch({ type }: { type: IssueType }) {
  const { viewer } = useViewer()
  const client = useQueryClient()
  const toggle = useMutation({
    mutationFn: () => api.updateIssueType(type.key, { enabled: !type.enabled, actor: viewer.name }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['issue-types'] }),
  })

  return (
    <Toggle
      checked={type.enabled}
      onChange={() => toggle.mutate()}
      label={`Check for ${type.title}`}
      disabled={toggle.isPending}
    />
  )
}

const FIELD = 'w-full rounded-lg border border-hair bg-bg px-3 text-[0.8125rem] text-ink'

/**
 * One check. Its name and description are the business's to word, so a person can edit
 * them here; each edit is kept in the audit log.
 */
function CheckRow({ type }: { type: IssueType }) {
  const { viewer } = useViewer()
  const client = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(type.title)
  const [description, setDescription] = useState(type.description)
  const save = useMutation({
    mutationFn: () => api.updateIssueType(type.key, { title, description, actor: viewer.name }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ['issue-types'] })
      setEditing(false)
    },
  })
  function start() {
    setTitle(type.title)
    setDescription(type.description)
    setEditing(true)
  }

  return (
    <>
      <tr>
        <td>
          <span className="flex items-center gap-1">
            <Link to={`/issues?type=${type.key}`} className="font-medium hover:underline">
              {type.title}
            </Link>
            <button
              type="button"
              aria-label={`Edit the name and description of ${type.title}`}
              aria-expanded={editing}
              onClick={() => (editing ? setEditing(false) : start())}
              className="grid size-6 shrink-0 place-items-center rounded-md text-muted transition-colors duration-150 ease-out hover:bg-raised hover:text-ink"
            >
              <Pencil size="0.875rem" strokeWidth={1.5} aria-hidden />
            </button>
          </span>
        </td>
        <td className="min-w-32 py-2 text-[0.8125rem] text-ink-2 whitespace-normal!">{type.description.replace(/\.$/, '')}</td>
        <td>
          <SeverityCell type={type} />
        </td>
        <td className="text-ink-2 capitalize max-2xl:hidden">{type.about}</td>
        <td className="text-ink-2 max-2xl:hidden">{type.origin === 'built_in' ? 'Built in' : type.created_by}</td>
        <td className="num">{type.open_count}</td>
        <td className="num">{Number(type.open_amount) > 0 ? money(type.open_amount) : ''}</td>
        <td className="text-right">
          <ToleranceCell type={type} />
        </td>
        <td>
          <Switch type={type} />
        </td>
      </tr>
      {editing && (
        // The editor opens under the check, across the whole table, so the fields have room.
        <tr>
          <td colSpan={9} className="h-auto! py-4! whitespace-normal!">
            <div className="grid grid-cols-1 gap-4 @[52rem]:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
              <label className="flex flex-col gap-1">
                <span className="text-[0.8125rem] font-medium">Name</span>
                <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={120} className={`${FIELD} h-9`} />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-[0.8125rem] font-medium">What it checks</span>
                <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} maxLength={400} className={`${FIELD} resize-none py-2`} />
              </label>
            </div>
            <div className="flex flex-wrap items-center gap-2 pt-3">
              <Button variant="primary" disabled={save.isPending || title.trim().length < 3 || description.trim().length < 8} onClick={() => save.mutate()}>
                Save
              </Button>
              <Button onClick={() => setEditing(false)}>Cancel</Button>
              {save.isError && <span className="text-[0.8125rem] text-neg">{save.error.message}</span>}
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

export function IssueTypes() {
  const client = useQueryClient()
  const types = useQuery({ queryKey: ['issue-types'], queryFn: api.issueTypes })
  const [adding, setAdding] = useState(false)
  const reread = useMutation({
    mutationFn: api.runReadingChecks,
    onSuccess: () => Promise.all(['issue-types', 'items', 'job'].map((key) => client.invalidateQueries({ queryKey: [key] }))),
  })
  const readingChecks = types.data?.some((type) => type.origin === 'reading' && type.enabled)

  return (
    <>
      <PageHead
        title="Checks"
        aside={types.data?.length}
        sub="What every sync looks for. The built-in checks compare the three systems; anyone who manages checks can add their own"
      >
        <div className="flex flex-wrap items-center gap-2">
          {reread.isError && <p className="text-[0.8125rem] text-neg">{reread.error.message}</p>}
          {/* A sync never calls the model, so reading checks only read new notes when asked. */}
          {readingChecks && (
            <Button disabled={reread.isPending} onClick={() => reread.mutate()}>
              {reread.isPending ? 'Reading notes' : 'Read new notes'}
            </Button>
          )}
          {!adding && (
            <Button variant="primary" onClick={() => setAdding(true)}>
              Add a check
            </Button>
          )}
        </div>
      </PageHead>
      {adding && <AddCheck onDone={() => setAdding(false)} />}
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
                    <th className="max-2xl:hidden">Added by</th>
                    <th className="num">Open</th>
                    <th className="num">Amount</th>
                    <th className="num">Tolerance</th>
                    <th>On</th>
                  </tr>
                </thead>
                <tbody>
                  {data.map((type) => (
                    <CheckRow key={type.key} type={type} />
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
