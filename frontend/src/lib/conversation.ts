import { useMutation, useMutationState, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from './api'
import type { AskPage } from './api'
import { useViewer } from './viewer'

/**
 * One person's conversation with the assistant. It is the same conversation
 * wherever it is opened: on the Ask page or in the pane beside any other page.
 * It is kept on the server, so it is still there after leaving or reloading.
 */
export function useConversation() {
  const { viewer } = useViewer()
  const client = useQueryClient()
  const historyKey = ['ask-history', viewer.name]
  const askKey = ['ask', viewer.name]

  const history = useQuery({ queryKey: historyKey, queryFn: () => api.askHistory(viewer.name) })

  const ask = useMutation({
    mutationKey: askKey,
    mutationFn: ({ question, page }: { question: string; page?: AskPage }) =>
      api.ask({ question, asked_by: viewer.name, owner: viewer.owner, page }),
    // Runs even if the page has been left, so the answer is waiting on return.
    onSuccess: () => client.invalidateQueries({ queryKey: historyKey }),
  })

  // Questions still being answered, and ones that failed, read from the shared
  // cache and not from a component. That is what lets a question outlive the page.
  const waiting = useMutationState({
    filters: { mutationKey: askKey, status: 'pending' },
    select: (mutation) => ({ id: mutation.mutationId, question: (mutation.state.variables as { question: string }).question }),
  })
  const failed = useMutationState({
    filters: { mutationKey: askKey, status: 'error' },
    select: (mutation) => ({
      id: mutation.mutationId,
      question: (mutation.state.variables as { question: string }).question,
      error: mutation.state.error instanceof ApiError ? mutation.state.error.message : 'The question could not be sent.',
    }),
  })

  const clear = useMutation({
    mutationFn: () => api.clearAskHistory(viewer.name),
    onSuccess: () => {
      const cache = client.getMutationCache()
      cache.findAll({ mutationKey: askKey }).forEach((mutation) => cache.remove(mutation))
      return client.invalidateQueries({ queryKey: historyKey })
    },
  })

  const saved = history.data ?? []
  const busy = waiting.length > 0

  return {
    history,
    saved,
    waiting,
    failed,
    busy,
    count: saved.length + failed.length + waiting.length,
    /** Sends a question, with the page it was asked from when there is one. */
    send(question: string, page?: AskPage) {
      const text = question.trim()
      if (text && !busy) ask.mutate({ question: text, page })
    },
    clear,
  }
}

export type Conversation = ReturnType<typeof useConversation>
