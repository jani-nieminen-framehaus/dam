import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import type { ImagesResponse } from '../types'
import { apiFetch } from './client'
import { useUIStore } from '../stores/useUIStore'

export function useSearch(query: string) {
  const addToast = useUIStore((s) => s.addToast)
  const result = useQuery({
    queryKey: ['search', query],
    queryFn: () =>
      apiFetch<ImagesResponse>(`/search?q=${encodeURIComponent(query)}&limit=1000`),
    enabled: query.length > 0,
    retry: false,
  })

  useEffect(() => {
    if (result.isError) {
      addToast('Search unavailable — SigLIP embedder failed to load', 'warning')
    }
  }, [result.isError, addToast])

  return result
}
