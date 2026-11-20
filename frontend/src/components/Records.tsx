import { useAssistant } from '../lib/assistant'
import type { Line } from '../lib/api'
import { money, shortDate, words } from '../lib/format'

const KINDS: Record<string, string> = {
  ops_cost: 'Ops cost entry',
  ledger_cost: 'Ledger cost entry',
  ledger_revenue: 'Ledger revenue entry',
  vendor_bill: 'Vendor bill',
  customer_invoice: 'Customer invoice',
}

// The records that are documents someone sent or received. These open as a preview in the side pane.
const DOCUMENTS = new Set(['customer_invoice', 'vendor_bill'])

/**
 * The records a problem rests on. An invoice or a bill opens its preview in the
 * side pane when clicked; ledger and cost entries are shown as they are.
 */
export function Records({ lines }: { lines: Line[] }) {
  const { view, show } = useAssistant()
  if (lines.length === 0) return <p className="text-ink-2">This is about something missing, so there is no record to show</p>

  const showing = view?.kind === 'document' ? view.lineId : null

  // The opened item is white, so its records sit in a grey well inside it.
  return (
    <div className="overflow-x-auto rounded-lg border border-hair bg-bg">
      <table className="data-table">
        <thead>
          <tr>
            <th>Record</th>
            <th>Description</th>
            <th>Number</th>
            <th>Dated</th>
            <th className="num">Amount</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((line) => {
            const document = DOCUMENTS.has(line.kind)
            const open = () =>
              show({ kind: 'document', lineId: line.id, documentKind: line.kind === 'vendor_bill' ? 'vendor_bill' : 'customer_invoice' })
            return (
              <tr
                key={line.id}
                className={document ? `clickable ${showing === line.id ? 'bg-card' : ''}` : undefined}
                onClick={document ? open : undefined}
              >
                <td>{KINDS[line.kind] ?? words(line.kind)}</td>
                <td className="text-ink-2">{line.company ?? line.description}</td>
                <td className="font-mono text-[0.8125rem] text-ink-2">{line.doc_number}</td>
                <td className="text-ink-2">{shortDate(line.line_date)}</td>
                <td className="num">{money(line.amount)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
