import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch } from './client'
import { useEffect, useRef } from 'react'

interface IngestStatus {
  status: 'idle' | 'ingesting'
  processed?: number
  total?: number
  current_file?: string
  stage?: string
}

export function useIngestStatus() {
  const qc = useQueryClient()
  const wasIngesting = useRef(false)

  const query = useQuery({
    queryKey: ['ingest-status'],
    queryFn: () => apiFetch<IngestStatus>('/ingest/status'),
    refetchInterval: 3000,
  })

  // When ingest finishes, refresh the image grid
  useEffect(() => {
    if (query.data?.status === 'ingesting') {
      wasIngesting.current = true
    } else if (wasIngesting.current && query.data?.status === 'idle') {
      wasIngesting.current = false
      qc.invalidateQueries({ queryKey: ['images'] })
      qc.invalidateQueries({ queryKey: ['filters'] })
      qc.invalidateQueries({ queryKey: ['stats'] })
    }
  }, [query.data?.status, qc])

  return query
}
