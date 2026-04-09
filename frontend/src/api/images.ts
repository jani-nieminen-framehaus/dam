import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { DamImage, ImagesResponse, FilterState } from '../types'
import { apiFetch, buildQueryString } from './client'
import { useUIStore } from '../stores/useUIStore'

const PAGE_SIZE = 50

export function useImages(filters: FilterState) {
  return useInfiniteQuery({
    queryKey: ['images', filters],
    queryFn: async ({ pageParam }) => {
      const params: Record<string, string | number | undefined> = {
        limit: PAGE_SIZE,
        ...filters,
      }
      if (pageParam) {
        params.cursor_date = pageParam.date
        params.cursor_id = pageParam.id
      }
      return apiFetch<ImagesResponse>(`/images${buildQueryString(params)}`)
    },
    initialPageParam: null as { date: string; id: number } | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
  })
}

export function usePatchImage() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, patch }: { id: number; patch: Partial<DamImage> }) => {
      return apiFetch<DamImage>(`/images/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(patch),
      })
    },
    onMutate: async ({ id, patch }) => {
      // Optimistic update — instant UI feedback during culling
      await qc.cancelQueries({ queryKey: ['images'] })
      qc.setQueriesData<{ pages: ImagesResponse[] }>(
        { queryKey: ['images'] },
        (old) => {
          if (!old) return old
          return {
            ...old,
            pages: old.pages.map((page) => ({
              ...page,
              images: page.images.map((img) =>
                img.id === id ? { ...img, ...patch } : img
              ),
            })),
          }
        }
      )
    },
    onError: () => {
      qc.invalidateQueries({ queryKey: ['images'] })
      useUIStore.getState().addToast('Failed to save — check connection', 'error')
    },
  })
}

export function useBulkPatch() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ ids, patch }: { ids: number[]; patch: Partial<DamImage> }) => {
      return apiFetch<{ updated: number }>('/images/bulk', {
        method: 'PATCH',
        body: JSON.stringify({ ids, patch }),
      })
    },
    onMutate: async ({ ids, patch }) => {
      await qc.cancelQueries({ queryKey: ['images'] })
      const idSet = new Set(ids)
      qc.setQueriesData<{ pages: ImagesResponse[] }>(
        { queryKey: ['images'] },
        (old) => {
          if (!old) return old
          return {
            ...old,
            pages: old.pages.map((page) => ({
              ...page,
              images: page.images.map((img) =>
                idSet.has(img.id) ? { ...img, ...patch } : img
              ),
            })),
          }
        }
      )
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['images'] })
    },
  })
}

export function useOpenExternal() {
  return useMutation({
    mutationFn: async ({ id, app }: { id: number; app?: string }) => {
      return apiFetch<{ success: boolean; action: string }>(`/images/${id}/open_external`, {
        method: 'POST',
        body: app ? JSON.stringify({ app }) : undefined,
      })
    },
    onError: () => {
      useUIStore.getState().addToast('Could not open file — is the volume mounted?', 'warning')
    },
  })
}

export function useOpenJpeg() {
  return useMutation({
    mutationFn: async (id: number) => {
      return apiFetch<{ success: boolean; action: string }>(`/images/${id}/open_jpeg`, {
        method: 'POST',
      })
    },
  })
}

export function useAddKeyword() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, keyword }: { id: number; keyword: string }) =>
      apiFetch<DamImage>(`/images/${id}/keywords`, {
        method: 'POST',
        body: JSON.stringify({ keyword }),
      }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['images'] }) },
    onError: () => { useUIStore.getState().addToast('Keyword update failed', 'error') },
  })
}

export function useRemoveKeyword() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, keyword }: { id: number; keyword: string }) =>
      apiFetch<DamImage>(`/images/${id}/keywords/${encodeURIComponent(keyword)}`, {
        method: 'DELETE',
      }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['images'] }) },
    onError: () => { useUIStore.getState().addToast('Keyword update failed', 'error') },
  })
}

export function useAddProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, name }: { id: number; name: string }) =>
      apiFetch<DamImage>(`/images/${id}/projects`, {
        method: 'POST',
        body: JSON.stringify({ name }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['images'] })
      qc.invalidateQueries({ queryKey: ['filters'] })
    },
  })
}

export function useRemoveProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, name }: { id: number; name: string }) =>
      apiFetch<DamImage>(`/images/${id}/projects/${encodeURIComponent(name)}`, {
        method: 'DELETE',
      }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['images'] }) },
  })
}
