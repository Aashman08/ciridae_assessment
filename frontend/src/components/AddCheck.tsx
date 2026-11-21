import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../lib/api'
import type { CheckDraft, CheckSubject } from '../lib/api'
import { money } from '../lib/format'
import { useViewer } from '../lib/viewer'
import { Working } from './Conversation'
import { Button, Card, CardHead, Empty } from './ui'

const FIELD = 'w-full rounded-lg border border-hair bg-bg px-3 text-ink placeholder:text-muted'

const LOOKS_AT: Record<CheckSubject, string> = {
  job: 'Each job',
  customer_invoice: 'Each customer invoice',
  vendor_bill: 'Each vendor bill',
}

/**
 * Where someone adds a check of their own. They say what to flag in their own words,
 * and nothing else: the assistant names it, works out what it looks at, its area and
 * severity, and whether it can be tested on the records (a rule, which then
 * runs on every sync with no model involved) or only by reading notes. "Try it" shows
 * exactly what it would flag today before anything is saved.
 */
export function AddCheck({ onDone }: { onDone: () => void }) {
  const { viewer } = useViewer()
  const client = useQueryClient()
  const [words, setWords] = useState('')
  const [tried, setTried] = useState<{ draft: CheckDraft; words: string } | null>(null)

  const attempt = useMutation({
    mutationFn: () => api.draftCheck({ words }),
    onSuccess: (draft) => setTried({ draft, words }),
  })
  const add = useMutation({
    mutationFn: () => {
      const { draft } = tried!
      return api.createCheck({
        title: draft.title, words: tried!.words, subject: draft.subject, approach: draft.approach as 'rule' | 'reading',
        rule: draft.rule, severity: draft.severity, about: draft.about, actor: viewer.name,
      })
    },
    onSuccess: async () => {
      await Promise.all(['issue-types', 'items', 'job', 'summary', 'activity'].map((key) => client.invalidateQueries({ queryKey: [key] })))
      onDone()
    },
  })

  // A changed description has to be tried again before it can be added.
  const current = tried && tried.words === words ? tried.draft : null
  const canTry = words.trim().length >= 8 && !attempt.isPending

  return (
    <Card>
      <CardHead title="Add a check" />
      <div className="flex flex-col gap-4 px-5 pb-5">
        <label className="flex flex-col gap-1">
          <span className="text-[0.8125rem] font-medium">What should it flag?</span>
          <textarea
            value={words}
            onChange={(e) => setWords(e.target.value)}
            rows={3}
            maxLength={600}
            placeholder="Sent invoices with more than $100,000 still open. Or: a customer says they dispute an invoice."
            className={`${FIELD} resize-none py-2`}
          />
        </label>

        <div className="flex flex-wrap items-center gap-2">
          <Button variant={current ? 'quiet' : 'primary'} disabled={!canTry} onClick={() => attempt.mutate()}>
            {current ? 'Try again' : 'Try it'}
          </Button>
          {current && current.approach !== 'cannot' && (
            <Button variant="primary" disabled={add.isPending} onClick={() => add.mutate()}>
              {add.isPending ? 'Adding' : 'Add this check'}
            </Button>
          )}
          <Button onClick={onDone}>Cancel</Button>
          {attempt.isError && <p className="text-[0.8125rem] text-neg">{attempt.error.message}</p>}
          {add.isError && <p className="text-[0.8125rem] text-neg">{add.error.message}</p>}
        </div>

        {attempt.isPending && <Working label="The assistant is working out how to run this check" />}

        {current && (
          <div className="flex flex-col gap-4 rounded-lg bg-bg p-4">
            {/* What the assistant made of the description, one fact each. */}
            <dl className="grid grid-cols-2 gap-x-6 gap-y-3 @[58rem]:grid-cols-4">
              {[
                ['Name', current.title],
                ['Looks at', LOOKS_AT[current.subject]],
                ['Area', current.about.charAt(0).toUpperCase() + current.about.slice(1)],
                ['Severity', current.severity === 'high' ? 'High' : 'Medium'],
              ].map(([label, value]) => (
                <div key={label} className="flex min-w-0 flex-col gap-1">
                  <dt className="text-[0.8125rem] font-medium">{label}</dt>
                  <dd className="text-ink-2">{value}</dd>
                </div>
              ))}
            </dl>
            <div className="flex flex-col gap-1">
              <p className="text-[0.8125rem] font-medium">
                {current.approach === 'rule'
                  ? 'Runs as a rule on every sync'
                  : current.approach === 'reading'
                    ? 'The assistant reads the notes for it'
                    : 'This cannot be checked'}
              </p>
              {current.reads_as && <p className="text-ink-2">{current.reads_as}</p>}
              <p className="text-[0.8125rem] text-ink-2">{current.reason}</p>
            </div>
            {current.approach !== 'cannot' && (
              <div className="flex flex-col gap-2">
                <p className="text-[0.8125rem] font-medium">
                  Today it would flag {current.would_flag.length} {current.would_flag.length === 1 ? 'record' : 'records'}
                </p>
                {current.would_flag.length === 0 ? (
                  <Empty>Nothing matches today</Empty>
                ) : (
                  <div className="min-w-0 overflow-x-auto rounded-lg border border-hair bg-card">
                    <table className="data-table dense">
                      <thead>
                        <tr>
                          <th>Record</th>
                          <th className="max-md:hidden">Job</th>
                          <th className="num">Amount</th>
                          <th>Why</th>
                        </tr>
                      </thead>
                      <tbody>
                        {current.would_flag.map((f) => (
                          <tr key={f.subject}>
                            <td className="font-mono text-[0.8125rem]">{f.subject}</td>
                            <td className="max-w-[16rem] truncate text-ink-2 max-md:hidden">{f.job_name ?? ''}</td>
                            <td className="num">{Number(f.amount) > 0 ? money(f.amount) : ''}</td>
                            <td className="w-full py-2! whitespace-normal! text-ink-2">{f.why}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </Card>
  )
}
