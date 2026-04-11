import { useQuery, useQueryClient } from '@tanstack/react-query'
import { apiFetch } from './client'
import { useEffect, useRef } from 'react'

export interface IngestStatus {
  status: 'idle' | 'scanning' | 'scanning_db' | 'thumbs' | 'copying' | 'error'
  current?: number
  total?: number
  current_path?: string
  dest_root?: string
  timestamp?: string
}

export interface TaggerStatus {
  status: 'idle' | 'tagging' | 'done' | 'error'
  current?: number
  total?: number
  current_path?: string
  current_id?: number
  last_keywords?: string[]
  timestamp?: string
}

export function useIngestStatus() {
  const qc = useQueryClient()
  const wasIngesting = useRef(false)

  const query = useQuery({
    queryKey: ['ingest-status'],
    queryFn: () => apiFetch<IngestStatus>('/ingest/status'),
    refetchInterval: 3000,
  })

  useEffect(() => {
    if (query.data?.status !== 'idle') {
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

export function useTagStatus() {
  const qc = useQueryClient()
  const wasTagging = useRef(false)

  const query = useQuery({
    queryKey: ['tagger-status'],
    queryFn: () => apiFetch<TaggerStatus>('/tagger/status'),
    refetchInterval: 3000,
  })

  useEffect(() => {
    if (query.data?.status === 'tagging') {
      wasTagging.current = true
    } else if (wasTagging.current && query.data?.status === 'done') {
      wasTagging.current = false
      qc.invalidateQueries({ queryKey: ['images'] })
      qc.invalidateQueries({ queryKey: ['filters'] })
      qc.invalidateQueries({ queryKey: ['stats'] })
    }
  }, [query.data?.status, qc])

  return query
}
