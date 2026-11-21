import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowRight } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { api } from '../lib/api'
import type { JobItems } from '../lib/api'
import { money } from '../lib/format'
import { Working } from './Conversation'
import { ItemTable } from './ItemTable'
import { useItemWork } from './useItemWork'
import { Button, Card, CardHead } from './ui'

/**
 * What needs doing on one job: the thing to do first, with a button that
 * starts it, then every item on the job.
 *
 * The first time a job's items are seen in their current state, the assistant
 * reviews them. Until it answers, and if it cannot, the standing rules decide.
 */
export function NextSteps({ jobNumber, items }: { jobNumber: string; items: JobItems | null }) {
  const client = useQueryClient()
  const work = useItemWork()

  const review = useMutation({
    mutationFn: () => api.reviewJob(jobNumber),
    onSuccess: () => Promise.all([client.invalidateQueries({ queryKey: ['job', jobNumber] }), client.invalidateQueries({ queryKey: ['items'] })]),
  })

  // Ask once for each state the items are in. A review that fails is not asked for again until something changes.
  const asked = useRef<string | null>(null)
  const state = items?.items.map((item) => `${item.key}${item.state}${item.note_count}${item.follow_up_on}${item.owner}`).join()
  const { mutate } = review
  useEffect(() => {
    if (!state || items?.reviewed_at || asked.current === state) return
    asked.current = state
    mutate()
  }, [state, items?.reviewed_at, mutate])

  if (!items) {
    return (
      <Card>
        <CardHead title="What needs doing" />
        <p className="px-5 pb-5 text-ink-2">Nothing on this job needs fixing</p>
      </Card>
    )
  }

  const first = items.suggestion && items.items.find((item) => item.key === items.suggestion?.item_key)

  return (
    <>
      <Card>
        <CardHead title="What needs doing">
          <p className="text-[0.8125rem] text-ink-2">
            {review.isPending
              ? null
              : items.reviewed_at
                ? 'Reviewed by the assistant'
                : review.isError
                  ? 'The assistant could not review this job, so the standing rules are shown'
                  : 'By the standing rules'}
          </p>
        </CardHead>

        {review.isPending ? (
          <div className="px-5 pb-4">
            <Working label="The assistant is reading this job's notes" />
          </div>
        ) : (
          first &&
          items.suggestion && (
            // The one thing to do first: what it is, which document and how much, why, and the
            // button that starts it. The step is named once, on the button.
            <div className="mx-5 mb-4 grid grid-cols-[auto_minmax(0,1fr)] items-start gap-x-4 gap-y-3 rounded-xl @[40rem]:items-center border border-brand/20 bg-brand-soft/50 p-4 @[40rem]:grid-cols-[auto_minmax(0,1fr)_auto]">
              <span aria-hidden className="grid size-10 place-items-center rounded-full bg-btn text-btn-ink">
                <ArrowRight size="1.125rem" strokeWidth={1.75} />
              </span>
              <div className="flex min-w-0 flex-col gap-1">
                <p className="text-xs leading-4 font-medium text-brand-ink">Do this first</p>
                <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <span className="font-medium">{first.title}</span>
                  {first.document && <span className="font-mono text-[0.8125rem] text-ink-2">{first.document}</span>}
                  {Number(first.amount) > 0 && <span className="font-mono text-[0.8125rem]">{money(first.amount)}</span>}
                </p>
                {items.suggestion.reason && <p className="text-[0.8125rem] text-ink-2">{items.suggestion.reason}</p>}
              </div>
              <div className="col-span-2 @[40rem]:col-span-1">
                <Button variant="primary" disabled={work.busy} onClick={() => work.start(first)}>
                  {items.suggestion.action.label}
                </Button>
              </div>
            </div>
          )
        )}

        <ItemTable items={items.items} />
      </Card>
      {work.dialogs}
    </>
  )
}
