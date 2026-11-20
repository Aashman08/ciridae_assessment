import { useQuery } from '@tanstack/react-query'
import { Fragment, useState } from 'react'
import { api } from '../lib/api'
import type { Line } from '../lib/api'
import { money, shortDate, words } from '../lib/format'
import { Button, Loaded } from './ui'

const KINDS: Record<string, string> = {
  ops_cost: 'Ops cost entry',
  ledger_cost: 'Ledger cost entry',
  ledger_revenue: 'Ledger revenue entry',
  vendor_bill: 'Vendor bill',
  customer_invoice: 'Customer invoice',
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

/** The records a problem rests on, each with a way to see the source system's own row. */
export function Records({ lines }: { lines: Line[] }) {
  const [open, setOpen] = useState<number | null>(null)
  if (lines.length === 0) return <p className="text-ink-2">This is about something missing, so there is no record to show</p>

  return (
    <div className="overflow-x-auto rounded-lg border border-hair bg-card">
      <table className="data-table">
        <thead>
          <tr>
            <th>Record</th>
            <th>Description</th>
            <th>Number</th>
            <th>Dated</th>
            <th className="num">Amount</th>
            <th>
              <span className="sr-only">Source row</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {lines.map((line) => (
            <Fragment key={line.id}>
              <tr>
                <td>{KINDS[line.kind] ?? words(line.kind)}</td>
                <td className="text-ink-2">{line.company ?? line.description}</td>
                <td className="font-mono text-[0.8125rem] text-ink-2">{line.doc_number}</td>
                <td className="text-ink-2">{shortDate(line.line_date)}</td>
                <td className="num">{money(line.amount)}</td>
                <td className="w-36 text-right">
                  <Button className="w-32" aria-expanded={open === line.id} onClick={() => setOpen(open === line.id ? null : line.id)}>
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
  )
}
