import { useUIStore } from '../../stores/useUIStore'

interface Props {
  totalFiltered: number
  totalLoaded: number
}

export function StatusBar({ totalFiltered, totalLoaded }: Props) {
  const { filters, selectedIds } = useUIStore()
  const activeFilters = Object.entries(filters).filter(([, v]) => v !== undefined)

  return (
    <div className="h-6 flex items-center px-3 gap-4 border-t border-[var(--border)] bg-[var(--bg2)] text-[11px] text-[var(--text-dim)] shrink-0">
      <span>{totalFiltered.toLocaleString()} images</span>
      <span>{totalLoaded.toLocaleString()} loaded</span>
      {selectedIds.size > 0 && (
        <span className="text-[var(--sel)]">{selectedIds.size} selected</span>
      )}
      {activeFilters.length > 0 && (
        <span>
          Filters: {activeFilters.map(([k, v]) => `${k}=${v}`).join(', ')}
        </span>
      )}
    </div>
  )
}
