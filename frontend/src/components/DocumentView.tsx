import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import type { DocumentParty } from '../lib/api'
import { longDate, money, words } from '../lib/format'
import { buttonClass } from '../lib/styles'
import { Loaded } from './ui'

/** A company, the person it is for, and where it is, as printed at the top of a document. */
function Party({ heading, party }: { heading: string; party: DocumentParty }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <p className="pb-1 text-xs leading-4 text-muted">{heading}</p>
      <p className="font-medium">{party.name}</p>
      {party.attention && (
        <p className="text-ink-2">
          Attn: {party.attention}
          {party.title && `, ${party.title}`}
        </p>
      )}
      {party.address.map((line) => (
        <p key={line} className="text-ink-2">
          {line}
        </p>
      ))}
      {party.email && <p className="break-all text-ink-2">{party.email}</p>}
    </div>
  )
}

/** A label and its value on one line, in the details block of a document. */
function Detail({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[6.5rem_minmax(0,1fr)] gap-3">
      <dt className="text-ink-2">{label}</dt>
      <dd>{children}</dd>
    </div>
  )
}

function Total({ label, amount, strong = false, attention = false }: { label: string; amount: string; strong?: boolean; attention?: boolean }) {
  return (
    <div className={`grid grid-cols-[minmax(0,1fr)_auto] gap-4 ${strong ? 'border-t border-hair pt-2 font-medium' : ''}`}>
      <dt className={strong ? '' : 'text-ink-2'}>{label}</dt>
      <dd className={`text-right font-mono text-[0.8125rem] tabular-nums ${attention ? 'text-accent-ink' : ''}`}>{money(amount)}</dd>
    </div>
  )
}

/**
 * An invoice or vendor bill in the side pane, laid out the way the paper copy reads:
 * its number and status, who it is from and to, its dates and terms, its lines,
 * totals, and the payments against it. It is built from the records in accounting;
 * the original file is not held here, and the pane says so.
 */
export function DocumentView({ lineId }: { lineId: number }) {
  const document = useQuery({ queryKey: ['document', lineId], queryFn: () => api.document(lineId) })

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-4">
      <Loaded query={document}>
        {(doc) => {
          const invoice = doc.kind === 'customer_invoice'
          const settled = Number(doc.balance) <= 0
          return (
            <article className="flex flex-col gap-6 rounded-xl border border-hair bg-card p-5 text-[0.8125rem] shadow-lift">
              <header className="flex items-start justify-between gap-4">
                <div>
                  <h3 className="text-xl leading-7 font-medium">{invoice ? 'Invoice' : 'Bill'}</h3>
                  <p className="font-mono">{doc.number}</p>
                </div>
                {doc.status && <p className="text-right text-ink-2">{words(doc.status)}</p>}
              </header>

              <Party heading={invoice ? 'From' : 'From the vendor'} party={doc.issuer} />
              <Party heading={invoice ? 'Bill to' : 'Billed to'} party={doc.recipient} />

              <dl className="flex flex-col gap-1">
                {doc.issued_on && <Detail label={invoice ? 'Invoice date' : 'Bill date'}>{longDate(doc.issued_on)}</Detail>}
                {doc.due_on && <Detail label="Due">{longDate(doc.due_on)}</Detail>}
                {doc.terms && <Detail label="Terms">{doc.terms}</Detail>}
                {doc.approved_on && <Detail label="Approved">{longDate(doc.approved_on)}</Detail>}
                {doc.sent_on && <Detail label="Sent">{longDate(doc.sent_on)}</Detail>}
                {doc.job_number && (
                  <Detail label="Job">
                    <span className="font-mono">{doc.job_number}</span>
                  </Detail>
                )}
              </dl>

              {(doc.job_name || doc.site.length > 0) && (
                <div className="flex flex-col gap-0.5">
                  <p className="pb-1 text-xs leading-4 text-muted">Job site</p>
                  {doc.job_name && <p>{doc.job_name}</p>}
                  {doc.site.map((line) => (
                    <p key={line} className="text-ink-2">
                      {line}
                    </p>
                  ))}
                </div>
              )}

              <div className="overflow-x-auto rounded-lg border border-hair">
                <table className="data-table dense">
                  <thead>
                    <tr>
                      <th>Description</th>
                      <th className="num">Qty</th>
                      <th className="num">Unit price</th>
                      <th className="num">Amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {doc.lines.length === 0 ? (
                      <tr>
                        <td colSpan={4} className="text-muted">
                          No lines are recorded
                        </td>
                      </tr>
                    ) : (
                      doc.lines.map((line, index) => (
                        <tr key={index}>
                          <td className="py-2! whitespace-normal!">{line.description}</td>
                          <td className="num">{line.quantity ? Number(line.quantity).toLocaleString('en-US') : ''}</td>
                          <td className="num">{line.unit_price ? money(line.unit_price) : ''}</td>
                          <td className="num">{money(line.amount)}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>

              <dl className="flex flex-col gap-1">
                {/* With no tax the subtotal is the total, so it is not repeated. */}
                {Number(doc.tax) > 0 && <Total label="Subtotal" amount={doc.subtotal} />}
                {Number(doc.tax) > 0 && <Total label="Tax" amount={doc.tax} />}
                <Total label="Total" amount={doc.total} strong />
                {Number(doc.paid) > 0 && <Total label="Paid" amount={doc.paid} />}
                <Total label={settled ? 'Paid in full' : 'Balance due'} amount={doc.balance} strong attention={!settled} />
              </dl>

              {doc.payments.length > 0 && (
                <div className="flex flex-col gap-2">
                  <p className="text-xs leading-4 text-muted">Payments received</p>
                  <div className="overflow-x-auto rounded-lg border border-hair">
                    <table className="data-table dense">
                      <thead>
                        <tr>
                          <th>Date</th>
                          <th>Reference</th>
                          <th className="num">Amount</th>
                        </tr>
                      </thead>
                      <tbody>
                        {doc.payments.map((payment, index) => (
                          <tr key={index}>
                            <td>{payment.on ? longDate(payment.on) : ''}</td>
                            <td className="font-mono text-ink-2">
                              {[payment.method, payment.reference].filter(Boolean).join(' ')}
                            </td>
                            <td className="num">{money(payment.amount)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {(doc.discount || doc.received_by_email || doc.files.length > 0) && (
                <div className="flex flex-col gap-2">
                  {doc.discount && (
                    <p>
                      <span className="text-ink-2">Early payment: </span>
                      {doc.discount}
                    </p>
                  )}
                  {doc.received_by_email && <p className="text-ink-2">{doc.received_by_email}</p>}
                  {doc.files.length > 0 && <p className="text-ink-2">On file: {doc.files.join(', ')}</p>}
                </div>
              )}

              {doc.notes.length > 0 && (
                <div className="flex flex-col gap-1">
                  <p className="text-xs leading-4 text-muted">Notes</p>
                  {doc.notes.map((note) => (
                    <p key={note}>{note}</p>
                  ))}
                </div>
              )}

              <footer className="flex flex-col items-start gap-3 border-t border-hair pt-4">
                <p className="text-xs leading-4 text-muted">
                  Laid out from the records in accounting. This is a preview, not the original {invoice ? 'invoice' : 'bill'}
                </p>
                {doc.job_number && (
                  <Link to={`/jobs/${doc.job_number}`} className={buttonClass()}>
                    Open job
                  </Link>
                )}
              </footer>
            </article>
          )
        }}
      </Loaded>
    </div>
  )
}
