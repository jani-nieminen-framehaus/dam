import { useQuery } from '@tanstack/react-query'
import type { ImagesResponse } from '../types'
import { apiFetch } from './client'

export function useSearch(query: string) {
  return useQuery({
    queryKey: ['search', query],
    queryFn: () =>
      apiFetch<ImagesResponse>(`/search?q=${encodeURIComponent(query)}&limit=200`),
    enabled: query.length > 0,
  })
}
