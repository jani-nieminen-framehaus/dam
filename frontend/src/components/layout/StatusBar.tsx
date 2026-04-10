import { Star } from 'lucide-react'
import { useUIStore } from '../../stores/useUIStore'
import { useBulkPatch } from '../../api/images'

interface Props {
  totalFiltered: number
  totalLoaded: number
}

export function StatusBar({ totalFiltered, totalLoaded }: Props) {
  const { filters, selectedIds, clearSelection } = useUIStore()
  const bulkPatch = useBulkPatch()
  const activeFilters = Object.entries(filters).filter(([, v]) => v !== undefined)
  const bulkMode = selectedIds.size > 1
  const ids = [...selectedIds]

  const doBulk = (patch: Record<string, unknown>) => {
    bulkPatch.mutate({ ids, patch })
  }

  return (
    <div className="h-7 flex items-center px-3 gap-3 border-t border-[var(--border)] bg-[var(--bg2)] text-[11px] text-[var(--text-dim)] shrink-0">
      {/* Left: counts & filters */}
      <span>{totalFiltered.toLocaleString()} images</span>
      <span>{totalLoaded.toLocaleString()} loaded</span>

      {activeFilters.length > 0 && (
        <div className="flex items-center gap-1">
          {activeFilters.map(([k, v]) => (
            <span key={k} className="px-1.5 py-0 rounded bg-[var(--bg3)] text-[var(--text-mid)]">
              {k}: {v}
            </span>
          ))}
        </div>
      )}

      {/* Bulk action bar */}
      {bulkMode && (
        <div className="flex items-center gap-2 ml-2 pl-2 border-l border-[var(--border)]">
          <span className="text-[var(--sel)] font-medium">{selectedIds.size} selected</span>
          <button onClick={() => doBulk({ pick: 'pick' })}
            className="px-1.5 py-0 rounded text-[10px] font-bold hover:bg-[var(--pick)] hover:text-black text-[var(--text-dim)]">
            Pick
          </button>
          <button onClick={() => doBulk({ pick: 'reject' })}
            className="px-1.5 py-0 rounded text-[10px] font-bold hover:bg-[var(--reject)] hover:text-white text-[var(--text-dim)]">
            Reject
          </button>
          <div className="flex gap-0">
            {[1, 2, 3, 4, 5].map((n) => (
              <button key={n} onClick={() => doBulk({ rating: n })} title={`Rate ${n}`}>
                <Star size={11} fill="none" stroke="var(--text-dim)" className="hover:stroke-[var(--accent)]" />
              </button>
            ))}
          </div>
          <button onClick={clearSelection}
            className="px-1.5 py-0 rounded text-[10px] text-[var(--text-dim)] hover:text-white">
            Clear
          </button>
        </div>
      )}

      {/* Single selection count (when not in bulk mode) */}
      {selectedIds.size === 1 && (
        <span className="text-[var(--sel)]">1 selected</span>
      )}

      <div className="flex-1" />
    </div>
  )
}
