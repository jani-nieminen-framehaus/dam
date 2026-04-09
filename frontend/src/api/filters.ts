import { useQuery } from '@tanstack/react-query'
import type { FiltersResponse, StatsResponse } from '../types'
import { apiFetch } from './client'

export function useFilters() {
  return useQuery({
    queryKey: ['filters'],
    queryFn: () => apiFetch<FiltersResponse>('/filters'),
    staleTime: 60_000,
  })
}

export function useStats() {
  return useQuery({
    queryKey: ['stats'],
    queryFn: () => apiFetch<StatsResponse>('/stats'),
    staleTime: 30_000,
  })
}

export function useInstalledApps() {
  return useQuery({
    queryKey: ['apps'],
    queryFn: () => apiFetch<{ apps: string[] }>('/apps'),
    staleTime: 300_000, // Apps don't change often
  })
}
