import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../lib/api'
import type { CheckDraft, CheckSubject } from '../lib/api'
import { money } from '../lib/format'
import { useViewer } from '../lib/viewer'
import { Working } from './Conversation'
import { Button, Card, CardHead, Empty, Select } from './ui'

const FIELD = 'w-full rounded-lg border border-hair bg-bg px-3 text-ink placeholder:text-muted'

const SUBJECTS: { value: CheckSubject; label: string }[] = [
  { value: 'job', label: 'Each job' },
  { value: 'customer_invoice', label: 'Each customer invoice' },
  { value: 'vendor_bill', label: 'Each vendor bill' },
]
const AREAS = [
  { value: 'cash', label: 'Cash' },
  { value: 'billing', label: 'Billing' },
  { value: 'cost', label: 'Cost' },
  { value: 'schedule', label: 'Schedule' },
  { value: 'ownership', label: 'Ownership' },
]
const SEVERITIES = [
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
]

/**
 * Where someone adds a check of their own. They say what to flag in their own words;
 * the assistant works out whether it can be tested on the records (a rule, which then
 * runs on every sync with no model involved) or only by reading notes. "Try it" shows
 * exactly what it would flag today before anything is saved.
 */
export function AddCheck({ onDone }: { onDone: () => void }) {
  const { viewer } = useViewer()
  const client = useQueryClient()
  const [title, setTitle] = useState('')
  const [words, setWords] = useState('')
  const [subject, setSubject] = useState<CheckSubject>('job')
  const [about, setAbout] = useState('cost')
  const [severity, setSeverity] = useState<'high' | 'medium'>('medium')
  const [tried, setTried] = useState<{ draft: CheckDraft; words: string; subject: CheckSubject } | null>(null)

  const attempt = useMutation({
    mutationFn: () => api.draftCheck({ words, subject }),
    onSuccess: (draft) => setTried({ draft, words, subject }),
  })
  const add = useMutation({
    mutationFn: () => {
      const draft = tried!.draft
      return api.createCheck({
        title, words: tried!.words, subject: tried!.subject, approach: draft.approach as 'rule' | 'reading',
        rule: draft.rule, severity, about, actor: viewer.name,
      })
    },
    onSuccess: async () => {
      await Promise.all(['issue-types', 'items', 'job', 'summary', 'activity'].map((key) => client.invalidateQueries({ queryKey: [key] })))
      onDone()
    },
  })

  // A changed description has to be tried again before it can be added.
  const current = tried && tried.words === words && tried.subject === subject ? tried.draft : null
  const canTry = words.trim().length >= 8 && !attempt.isPending
  const canAdd = current && current.approach !== 'cannot' && title.trim().length >= 3 && !add.isPending

  return (
    <Card>
      <CardHead title="Add a check" />
      <div className="flex flex-col gap-4 px-5 pb-5">
        <div className="grid grid-cols-1 gap-4 @[58rem]:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <label className="flex flex-col gap-1">
            <span className="text-[0.8125rem] font-medium">Name</span>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Large invoice still open"
              maxLength={120}
              className={`${FIELD} h-9`}
            />
          </label>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Select layout="stacked" label="Looks at" value={subject} onChange={(v) => setSubject(v as CheckSubject)} options={SUBJECTS} />
            <Select layout="stacked" label="Area" value={about} onChange={setAbout} options={AREAS} />
            <Select layout="stacked" label="Severity" value={severity} onChange={(v) => setSeverity(v as 'high' | 'medium')} options={SEVERITIES} />
          </div>
        </div>
        <label className="flex flex-col gap-1">
          <span className="text-[0.8125rem] font-medium">What should it flag?</span>
          <textarea
            value={words}
            onChange={(e) => setWords(e.target.value)}
            rows={3}
            maxLength={600}
            placeholder="Sent invoices with more than $100,000 still open. Or: the customer says they dispute the invoice."
            className={`${FIELD} resize-none py-2`}
          />
        </label>

        <div className="flex flex-wrap items-center gap-2">
          <Button variant={current ? 'quiet' : 'primary'} disabled={!canTry} onClick={() => attempt.mutate()}>
            {current ? 'Try again' : 'Try it'}
          </Button>
          {current && current.approach !== 'cannot' && (
            <Button variant="primary" disabled={!canAdd} onClick={() => add.mutate()}>
              {add.isPending ? 'Adding' : 'Add this check'}
            </Button>
          )}
          <Button onClick={onDone}>Cancel</Button>
          {attempt.isError && <p className="text-[0.8125rem] text-neg">{attempt.error.message}</p>}
          {add.isError && <p className="text-[0.8125rem] text-neg">{add.error.message}</p>}
        </div>

        {attempt.isPending && <Working label="The assistant is working out how to run this check" />}

        {current && (
          <div className="flex flex-col gap-3 rounded-lg bg-bg p-4">
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
