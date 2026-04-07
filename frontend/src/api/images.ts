import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { DamImage, ImagesResponse, FilterState } from '../types'
import { apiFetch, buildQueryString } from './client'

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
      // Rollback on failure — refetch from server
      qc.invalidateQueries({ queryKey: ['images'] })
    },
  })
}
