import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from './api'
import type { Item, ItemUpdate } from './api'
import { useViewer } from './viewer'

/** How long a follow-up runs after a message has gone, when no better date is known. */
export const FOLLOW_UP_WORKING_DAYS = 5

/**
 * Does one thing to an item, then refetches what is on screen, since an action
 * moves it between lists and changes totals. A drafted message or a bill
 * suggestion already in the side pane is left alone.
 */
export function useItemAction() {
  const { viewer } = useViewer()
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ item, ...body }: { item: Item } & Omit<ItemUpdate, 'actor'>) =>
      api.actOnItem(item.key, { ...body, actor: viewer.name }),
    onSuccess: () => client.invalidateQueries({ predicate: (query) => query.queryKey[0] !== 'draft' && query.queryKey[0] !== 'coding' }),
  })
}

/** What an item is about, in a few words: its document, or the job for a gap. */
export function about(item: Item): string {
  return item.document ?? item.job_number ?? ''
}
