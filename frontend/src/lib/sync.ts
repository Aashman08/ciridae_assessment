import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './api'

/** The most recent sync, if there has been one. */
export function useLatestSync() {
  return useQuery({ queryKey: ['latest-sync'], queryFn: api.latestSync, select: (page) => page.data[0] ?? null })
}

/** Runs a sync, then refetches everything on screen, since any figure may have changed. */
export function useRunSync() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: api.runSync,
    onSuccess: () => client.invalidateQueries(),
  })
}
