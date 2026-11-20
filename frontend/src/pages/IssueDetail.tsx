import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Fragment, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { UpdateDialog } from '../components/UpdateDialog'
import { Button, Card, CardHead, Empty, Loaded, PageHead } from '../components/ui'
import { api } from '../lib/api'
import type { IssueDetail as Issue } from '../lib/api'
import { dateTime, longDate, money, shortDate, words } from '../lib/format'
import { useViewer } from '../lib/viewer'

const KINDS: Record<string, string> = {
  ops_cost: 'Ops cost entry',
  ledger_cost: 'Ledger cost entry',
  ledger_revenue: 'Ledger revenue entry',
  vendor_bill: 'Vendor bill',
  customer_invoice: 'Customer invoice',
}

const EVENTS: Record<string, string> = {
  opened: 'Opened',
  commented: 'Note',
  assigned: 'Assigned',
  follow_up: 'Follow-up',
  resolved: 'Resolved',
  reopened: 'Reopened',
  cleared: 'Cleared',
}

const SYSTEMS: Record<string, string> = { crm: 'CRM', project: 'Project system', accounting: 'Accounting' }

/** The untouched row from the source system that a figure came from. */
function SourceRow({ recordId }: { recordId: number }) {
  const record = useQuery({ queryKey: ['source-record', recordId], queryFn: () => api.sourceRecord(recordId) })

  return (
    <Loaded query={record}>
      {(data) => (
        <div className="px-5 py-4">
          <p className="pb-3 text-xs leading-4 text-muted">
            Exactly as {SYSTEMS[data.system] ?? data.system} returned it, from its {words(data.table_name).toLowerCase()} table
          </p>
          <dl className="grid grid-cols-1 gap-x-8 gap-y-1 font-mono text-xs leading-5 sm:grid-cols-2">
            {Object.entries(data.payload)
              .filter(([, value]) => value !== null && value !== '')
              .map(([field, value]) => (
                <div key={field} className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] gap-3">
                  <dt className="truncate text-muted">{field}</dt>
                  <dd className="truncate">{String(value)}</dd>
                </div>
              ))}
          </dl>
        </div>
      )}
    </Loaded>
  )
}

function Evidence({ issue }: { issue: Issue }) {
  const [open, setOpen] = useState<number | null>(null)

  return (
    <Card>
      <CardHead title="The records behind this" />
      {issue.evidence.length === 0 ? (
        <Empty>This issue is about something missing, so there is no record to show</Empty>
      ) : (
        <div className="overflow-x-auto">
          <table className="data-table">
            <thead>
              <tr>
                <th>Record</th>
                <th>Description</th>
                <th>Number</th>
                <th>Date</th>
                <th className="num">Amount</th>
                <th>
                  <span className="sr-only">Source row</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {issue.evidence.map((line) => (
                <Fragment key={line.id}>
                  <tr>
                    <td>{KINDS[line.kind] ?? words(line.kind)}</td>
                    <td className="text-ink-2">{line.description}</td>
                    <td className="font-mono text-[0.8125rem] text-ink-2">{line.doc_number}</td>
                    <td className="text-ink-2">{shortDate(line.line_date)}</td>
                    <td className="num">{money(line.amount)}</td>
                    <td className="w-36 text-right">
                      <Button
                        className="w-32"
                        aria-expanded={open === line.id}
                        onClick={() => setOpen(open === line.id ? null : line.id)}
                      >
                        {open === line.id ? 'Hide source row' : 'Show source row'}
                      </Button>
                    </td>
                  </tr>
                  {open === line.id && (
                    <tr>
                      <td colSpan={6} className="h-auto! bg-raised p-0! whitespace-normal!">
                        <SourceRow recordId={line.source_record_id} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}

// Why the person named as owner has the issue.
const OWNER_ROLES: Record<Issue['owner_role'], string> = {
  ops_manager: "The job's ops manager",
  account_executive: "The job's account executive, because it has no ops manager",
  finance: 'Finance, because the job has no ops manager or account executive',
  assigned: 'Assigned by hand',
}

/** Who has it, why, and the dates that matter, as one strip across the top of the page. */
function Ownership({ issue }: { issue: Issue }) {
  const facts: { label: string; value: string; figure?: boolean; attention?: boolean }[] = [
    { label: 'Owner', value: issue.owner },
    { label: 'Why them', value: OWNER_ROLES[issue.owner_role] },
    { label: 'Severity', value: words(issue.severity) },
    { label: 'First found', value: longDate(issue.first_seen_on) },
  ]
  if (issue.due_on) facts.push({ label: 'Due', value: longDate(issue.due_on) })
  if (issue.days_late) facts.push({ label: 'Days late', value: String(issue.days_late), figure: true, attention: true })
  facts.push({ label: 'Follow up on', value: issue.follow_up_on ? longDate(issue.follow_up_on) : 'No date set' })

  return (
    <Card>
      <dl className="grid grid-cols-[repeat(auto-fit,minmax(11rem,1fr))] gap-x-6 gap-y-4 p-5">
        {facts.map((fact) => (
          <div key={fact.label} className="flex min-w-0 flex-col gap-1">
            <dt className="text-[0.8125rem] text-ink-2">{fact.label}</dt>
            <dd className={`${fact.figure ? 'font-mono text-[0.8125rem] tabular-nums' : ''} ${fact.attention ? 'text-accent-ink' : ''}`}>
              {fact.value}
            </dd>
          </div>
        ))}
      </dl>
    </Card>
  )
}

/** The other open issues about the same invoice or bill. It is the same money each time. */
function SameDocument({ issue }: { issue: Issue }) {
  const navigate = useNavigate()
  if (issue.related.length === 0) return null

  return (
    <Card>
      <CardHead title={`Also flagged on ${issue.document}`} />
      <p className="px-5 pb-3 text-[0.8125rem] text-ink-2">
        These are about the same document, so their amounts are the same dollars and should not be added together
      </p>
      <div className="overflow-x-auto">
        <table className="data-table">
          <thead>
            <tr>
              <th>Issue</th>
              <th>Severity</th>
              <th className="num">Amount</th>
            </tr>
          </thead>
          <tbody>
            {issue.related.map((other) => (
              <tr key={other.id} className="clickable" onClick={() => navigate(`/issues/${other.id}`)}>
                <td>
                  <Link to={`/issues/${other.id}`} className="font-medium" onClick={(e) => e.stopPropagation()}>
                    {other.title}
                  </Link>
                </td>
                <td className={`capitalize ${other.severity === 'high' ? '' : 'text-ink-2'}`}>{other.severity}</td>
                <td className="num">{Number(other.amount) > 0 ? money(other.amount) : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

function History({ issue }: { issue: Issue }) {
  return (
    <Card>
      <CardHead title="History" />
      <ol className="flex flex-col gap-4 px-5 pb-5">
        {issue.events.map((event) => (
          <li key={event.id} className="text-[0.8125rem]">
            <p>
              <span className="font-medium">{EVENTS[event.kind] ?? event.kind}</span>
              <span className="text-ink-2"> by {event.actor === 'system' ? 'a sync' : event.actor}</span>
            </p>
            {event.note && <p className="text-ink-2">{event.note}</p>}
            <p className="font-mono text-xs leading-4 text-muted">{dateTime(event.created_at)}</p>
          </li>
        ))}
      </ol>
    </Card>
  )
}

export function IssueDetail() {
  const { issueId = '' } = useParams()
  const id = Number(issueId)
  const { viewer } = useViewer()
  const client = useQueryClient()
  const [resolving, setResolving] = useState(false)
  const issue = useQuery({ queryKey: ['issue', id], queryFn: () => api.issue(id) })

  const reopen = useMutation({
    mutationFn: () => api.actOnIssue(id, { action: 'reopen', actor: viewer.name }),
    onSuccess: () => client.invalidateQueries(),
  })

  return (
    <Loaded query={issue}>
      {(data) => {
        const active = data.status === 'open' || data.status === 'assigned'
        return (
          <>
            <PageHead
              title={data.title}
              aside={Number(data.amount) > 0 ? money(data.amount) : undefined}
              sub={
                <span className="flex flex-wrap gap-x-4 gap-y-1">
                  {data.job_number ? (
                    <Link to={`/jobs/${data.job_number}`} className="hover:underline">
                      {data.job_name} <span className="font-mono text-[0.8125rem]">{data.job_number}</span>
                    </Link>
                  ) : (
                    <span>No job</span>
                  )}
                  <span className={active ? 'text-accent-ink' : ''}>{words(data.status)}</span>
                </span>
              }
            >
              {active ? (
                <Button variant="primary" onClick={() => setResolving(true)}>
                  Log update
                </Button>
              ) : (
                <Button disabled={reopen.isPending} onClick={() => reopen.mutate()}>
                  Reopen
                </Button>
              )}
            </PageHead>

            <Ownership issue={data} />

            <div className="grid grid-cols-1 items-start gap-4 2xl:grid-cols-[minmax(0,1fr)_25rem]">
              <div className="flex min-w-0 flex-col gap-4">
                <Card className="flex flex-col gap-4 p-5">
                  <div>
                    <h2 className="pb-1 font-medium">What is wrong</h2>
                    <p className="max-w-prose text-ink-2">{data.detail}</p>
                  </div>
                  <div>
                    <h2 className="pb-1 font-medium">{active ? 'What to do' : 'How it was resolved'}</h2>
                    <p className="max-w-prose text-ink-2">
                      {active ? data.next_step : (data.resolution_note ?? 'A later sync no longer found this problem.')}
                    </p>
                  </div>
                </Card>
                <SameDocument issue={data} />
                <Evidence issue={data} />
              </div>
              <History issue={data} />
            </div>

            {resolving && <UpdateDialog issue={data} onClose={() => setResolving(false)} />}
          </>
        )
      }}
    </Loaded>
  )
}
