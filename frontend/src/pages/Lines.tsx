import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Card, Empty, Loaded, PageHead, Pager } from '../components/ui'
import { api } from '../lib/api'
import type { Line } from '../lib/api'
import { daysBetween, money, shortDate, words } from '../lib/format'
import { useViewer } from '../lib/viewer'

const PAGE_SIZE = 25

function JobCell({ line }: { line: Line }) {
  return line.job_number ? (
    <span className="font-mono text-xs text-muted">{line.job_number}</span>
  ) : (
    <span className="text-accent-ink">No job</span>
  )
}

function InvoiceRows({ lines, asOf }: { lines: Line[]; asOf: string }) {
  const navigate = useNavigate()
  return (
    <table className="data-table">
      <thead>
        <tr>
          <th>Invoice</th>
          <th>Customer</th>
          <th>Job</th>
          <th>Status</th>
          <th>Due</th>
          <th className="num">Days late</th>
          <th className="num">Amount</th>
          <th className="num max-2xl:hidden">Paid</th>
          <th className="num">Open</th>
        </tr>
      </thead>
      <tbody>
        {lines.map((line) => {
          const sent = line.status === 'SENT'
          const late = sent && Number(line.open_amount) > 0 && line.due_date !== null && line.due_date < asOf
          return (
            <tr key={line.id} className="clickable" onClick={() => line.job_number && navigate(`/jobs/${line.job_number}`)}>
              <td className="font-mono text-[0.8125rem]">{line.doc_number}</td>
              <td>{line.company}</td>
              <td>
                <JobCell line={line} />
              </td>
              <td className={sent ? 'text-ink-2' : 'text-accent-ink'}>{words(line.status)}</td>
              <td className="text-ink-2">{shortDate(line.due_date)}</td>
              <td className="num text-accent-ink">{late && line.due_date ? daysBetween(asOf, line.due_date) : ''}</td>
              <td className="num">{money(line.amount)}</td>
              <td className="num max-2xl:hidden">{money(line.paid_amount)}</td>
              <td className="num">{money(line.open_amount)}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

function BillRows({ lines }: { lines: Line[] }) {
  const navigate = useNavigate()
  return (
    <table className="data-table">
      <thead>
        <tr>
          <th>Bill</th>
          <th>Vendor</th>
          <th>Job</th>
          <th>Status</th>
          <th>Dated</th>
          <th>Due</th>
          <th className="num">Amount</th>
        </tr>
      </thead>
      <tbody>
        {lines.map((line) => (
          <tr
            key={line.id}
            className={line.job_number ? 'clickable' : undefined}
            onClick={() => line.job_number && navigate(`/jobs/${line.job_number}`)}
          >
            <td className="font-mono text-[0.8125rem]">{line.doc_number}</td>
            <td>{line.company ?? line.description}</td>
            <td>
              <JobCell line={line} />
            </td>
            <td className="text-ink-2">{words(line.status)}</td>
            <td className="text-ink-2">{shortDate(line.line_date)}</td>
            <td className="text-ink-2">{shortDate(line.due_date)}</td>
            <td className="num">{money(line.amount)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** Customer invoices or vendor bills across jobs, largest open amount first. */
export function Lines({ kind }: { kind: 'customer_invoice' | 'vendor_bill' }) {
  const { viewer } = useViewer()
  const [params, setParams] = useSearchParams()
  const offset = Number(params.get('offset') ?? 0)
  const invoices = kind === 'customer_invoice'

  const summary = useQuery({ queryKey: ['summary', viewer.owner], queryFn: () => api.summary(viewer.owner) })
  const lines = useQuery({
    queryKey: ['lines', kind, viewer.owner, offset],
    queryFn: () => api.lines({ kind, owner: viewer.owner, offset, limit: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  })

  return (
    <>
      <PageHead
        title={invoices ? 'Customer invoices' : 'Vendor bills'}
        aside={lines.data?.total}
        sub={invoices ? 'Largest open amount first' : 'None of these has a ledger entry yet'}
      />
      <Card>
        <Loaded query={lines}>
          {(page) =>
            page.data.length === 0 ? (
              <Empty>{invoices ? 'No invoices yet' : 'No vendor bills yet'}</Empty>
            ) : (
              <>
                <div className="overflow-x-auto">
                  {invoices ? <InvoiceRows lines={page.data} asOf={summary.data?.as_of ?? ''} /> : <BillRows lines={page.data} />}
                </div>
                <Pager
                  offset={offset}
                  limit={PAGE_SIZE}
                  total={page.total}
                  onChange={(value) => setParams(value ? { offset: String(value) } : {})}
                />
              </>
            )
          }
        </Loaded>
      </Card>
    </>
  )
}
