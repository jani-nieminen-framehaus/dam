import { create } from 'zustand'
import type { FilterState } from '../types'

interface UIState {
  // Sidebar
  sidebarOpen: boolean
  toggleSidebar: () => void

  // Selection
  selectedId: number | null
  selectedIds: Set<number>
  select: (id: number) => void
  toggleSelect: (id: number) => void
  clearSelection: () => void

  // Lightbox
  lightboxIndex: number | null
  openLightbox: (index: number) => void
  closeLightbox: () => void
  setLightboxIndex: (index: number) => void

  // Filters (UI state that drives TanStack Query key)
  filters: FilterState
  setFilter: (key: keyof FilterState, value: string | number | undefined) => void
  clearFilters: () => void

  // View
  thumbSize: number
  setThumbSize: (size: number) => void
}

export const useUIStore = create<UIState>((set) => ({
  sidebarOpen: true,
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),

  selectedId: null,
  selectedIds: new Set(),
  select: (id) => set({ selectedId: id, selectedIds: new Set([id]) }),
  toggleSelect: (id) =>
    set((s) => {
      const next = new Set(s.selectedIds)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return { selectedIds: next, selectedId: id }
    }),
  clearSelection: () => set({ selectedId: null, selectedIds: new Set() }),

  lightboxIndex: null,
  openLightbox: (index) => set({ lightboxIndex: index }),
  closeLightbox: () => set({ lightboxIndex: null }),
  setLightboxIndex: (index) => set({ lightboxIndex: index }),

  filters: {},
  setFilter: (key, value) =>
    set((s) => ({
      filters: { ...s.filters, [key]: value || undefined },
    })),
  clearFilters: () => set({ filters: {} }),

  thumbSize: 200,
  setThumbSize: (size) => set({ thumbSize: size }),
}))
