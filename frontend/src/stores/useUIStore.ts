import { create } from 'zustand'
import type { DamImage, FilterState } from '../types'

export type ToastType = 'error' | 'warning' | 'info' | 'success'

export interface Toast {
  id: string
  message: string
  type: ToastType
}

interface UIState {
  // Toasts
  toasts: Toast[]
  addToast: (message: string, type?: ToastType) => void
  dismissToast: (id: string) => void

  // Sidebar
  sidebarOpen: boolean
  toggleSidebar: () => void

  // Search
  searchQuery: string
  setSearchQuery: (q: string) => void
  clearSearch: () => void

  // Selection
  selectedId: number | null
  selectedIds: Set<number>
  lastClickedIndex: number | null
  select: (id: number, index?: number) => void
  toggleSelect: (id: number) => void
  rangeSelect: (fromIndex: number, toIndex: number, allImages: DamImage[]) => void
  selectAll: (allImages: DamImage[]) => void
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

  // External apps
  lastOpenApp: string | undefined
  setLastOpenApp: (app: string | undefined) => void

  // Sort
  sortBy: string
  sortDir: 'asc' | 'desc'
  setSortBy: (s: string) => void
  toggleSortDir: () => void

  // Help
  helpOpen: boolean
  toggleHelp: () => void

  // View mode
  viewMode: 'grid' | 'list'
  setViewMode: (mode: 'grid' | 'list') => void

  // Thumb size (grid only)
  thumbSize: number
  setThumbSize: (size: number) => void
}

export const useUIStore = create<UIState>((set) => ({
  toasts: [],
  addToast: (message, type = 'error') => {
    const id = `${Date.now()}-${Math.random()}`
    set((s) => ({ toasts: [...s.toasts, { id, message, type }] }))
    if (type !== 'error') {
      setTimeout(() => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })), 5000)
    }
  },
  dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),

  sidebarOpen: true,
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),

  searchQuery: '',
  setSearchQuery: (q) => set({ searchQuery: q }),
  clearSearch: () => set({ searchQuery: '' }),

  selectedId: null,
  selectedIds: new Set(),
  lastClickedIndex: null,
  select: (id, index) => set({ selectedId: id, selectedIds: new Set([id]), lastClickedIndex: index ?? null }),
  toggleSelect: (id) =>
    set((s) => {
      const next = new Set(s.selectedIds)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return { selectedIds: next, selectedId: id }
    }),
  rangeSelect: (fromIndex, toIndex, allImages) =>
    set((s) => {
      const lo = Math.min(fromIndex, toIndex)
      const hi = Math.max(fromIndex, toIndex)
      const next = new Set(s.selectedIds)
      for (let i = lo; i <= hi; i++) {
        if (allImages[i]) next.add(allImages[i].id)
      }
      return { selectedIds: next, selectedId: allImages[toIndex]?.id ?? s.selectedId }
    }),
  selectAll: (allImages) =>
    set(() => ({
      selectedIds: new Set(allImages.map((img) => img.id)),
      selectedId: allImages[allImages.length - 1]?.id ?? null,
    })),
  clearSelection: () => set({ selectedId: null, selectedIds: new Set(), lastClickedIndex: null }),

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

  lastOpenApp: undefined,
  setLastOpenApp: (app) => set({ lastOpenApp: app }),

  sortBy: 'date_taken',
  sortDir: 'desc',
  setSortBy: (s) => set({ sortBy: s }),
  toggleSortDir: () => set((prev) => ({ sortDir: prev.sortDir === 'desc' ? 'asc' : 'desc' })),

  helpOpen: false,
  toggleHelp: () => set((s) => ({ helpOpen: !s.helpOpen })),

  viewMode: 'grid',
  setViewMode: (mode) => set({ viewMode: mode }),

  thumbSize: 200,
  setThumbSize: (size) => set({ thumbSize: size }),
}))
