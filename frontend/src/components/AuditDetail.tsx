import { Link } from 'react-router-dom'
import { who } from '../lib/activity'
import type { ActivityEntry } from '../lib/api'
import { useAssistant } from '../lib/assistant'
import { buttonClass } from '../lib/styles'
import { Button } from './ui'

const HEADING = 'text-[0.8125rem] font-medium text-ink'
const WHERE = { project: 'The project system', accounting: 'Accounting', app: 'This app' } as const

function exactly(timestamp: string): string {
  return new Date(timestamp).toLocaleString('en-US', {
    weekday: 'short', day: 'numeric', month: 'long', year: 'numeric', hour: 'numeric', minute: '2-digit', second: '2-digit',
  })
}

/**
 * One audit log entry in full, in the side pane: what was done, by whom and exactly
 * when, what it changed from and to, the note or reason in full, and what it was done
 * to, with a way to open the job or the document.
 */
export function AuditDetail({ entry }: { entry: ActivityEntry }) {
  const { show } = useAssistant()
  // Document and job numbers are set in the figures face; a check's name is words.
  const numbered = Boolean(entry.document) || entry.record === entry.job_number
  const facts: [string, string][] = [
    ['Who', who(entry.by)],
    ['When', exactly(entry.at)],
    ['Where', WHERE[entry.source]],
    ...(entry.record ? ([['Record', entry.record]] as [string, string][]) : []),
    ...(entry.about && entry.about !== entry.record ? ([['Check', entry.about]] as [string, string][]) : []),
    ...(entry.job_name ? ([['Job', entry.job_name]] as [string, string][]) : []),
  ]

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto p-4">
      <section className="flex flex-col gap-4 rounded-xl border border-hair bg-card p-5">
        <h3 className="text-lg leading-6 font-medium">{entry.action}</h3>
        <dl className="flex flex-col gap-2">
          {facts.map(([label, value]) => (
            <div key={label} className="grid grid-cols-[6rem_minmax(0,1fr)] gap-3">
              <dt className="text-[0.8125rem] text-muted">{label}</dt>
              <dd className={label === 'Record' && numbered ? 'font-mono text-[0.8125rem]' : 'text-[0.8125rem]'}>{value}</dd>
            </div>
          ))}
        </dl>
      </section>

      {entry.changes.length > 0 && (
        <section className="flex flex-col gap-2">
          <h4 className={HEADING}>What changed</h4>
          <div className="overflow-hidden rounded-xl border border-hair bg-card">
            <table className="data-table dense">
              <thead>
                <tr>
                  <th>What</th>
                  <th>Before</th>
                  <th>After</th>
                </tr>
              </thead>
              <tbody>
                {entry.changes.map((change) => (
                  <tr key={change.field}>
                    <td>{change.field}</td>
                    <td className="text-ink-2">{change.before ?? 'None'}</td>
                    <td className="font-medium">{change.after ?? 'None'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {entry.text && (
        <section className="flex flex-col gap-2">
          <h4 className={HEADING}>{entry.by === 'assistant' ? 'Why' : entry.kind === 'setting_changed' ? 'Change' : 'Note'}</h4>
          <p className="rounded-xl border border-hair bg-card p-4 text-[0.8125rem] whitespace-pre-wrap text-ink-2">{entry.text}</p>
        </section>
      )}

      {(entry.job_number || entry.document_line_id) && (
        <div className="flex flex-wrap gap-2">
          {entry.job_number && (
            <Link to={`/jobs/${entry.job_number}`} className={buttonClass()}>
              Open job
            </Link>
          )}
          {entry.document_line_id && entry.document_kind && (
            <Button onClick={() => show({ kind: 'document', lineId: entry.document_line_id!, documentKind: entry.document_kind! })}>
              View {entry.document_kind === 'customer_invoice' ? 'invoice' : 'bill'}
            </Button>
          )}
        </div>
      )}
    </div>
  )
}
