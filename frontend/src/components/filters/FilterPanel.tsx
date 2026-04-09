import { useFilters } from '../../api/filters'
import { useUIStore } from '../../stores/useUIStore'

function FilterSelect({ label, value, options, onChange }: {
  label: string
  value: string | undefined
  options: string[]
  onChange: (v: string | undefined) => void
}) {
  return (
    <div className="mb-3">
      <label className="block text-[11px] text-[var(--text-dim)] mb-1 uppercase tracking-wider">
        {label}
      </label>
      <select
        value={value || ''}
        onChange={(e) => onChange(e.target.value || undefined)}
        className="w-full bg-[var(--bg3)] text-[var(--text)] border border-[var(--border)] rounded px-2 py-1 text-sm"
      >
        <option value="">All</option>
        {options.map((opt) => (
          <option key={opt} value={opt}>{opt}</option>
        ))}
      </select>
    </div>
  )
}

export function FilterPanel() {
  const { filters, setFilter, clearFilters } = useUIStore()
  const { data } = useFilters()

  if (!data) return <div className="p-3 text-[var(--text-dim)]">Loading filters...</div>

  const hasActiveFilters = Object.values(filters).some(Boolean)

  return (
    <div className="p-3 overflow-y-auto h-full">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xs font-bold uppercase tracking-wider text-[var(--text-mid)]">Filters</h2>
        {hasActiveFilters && (
          <button
            onClick={clearFilters}
            className="text-[10px] text-[var(--accent)] hover:underline"
          >
            Clear all
          </button>
        )}
      </div>

      <FilterSelect label="Camera" value={filters.camera} options={data.cameras} onChange={(v) => setFilter('camera', v)} />
      <FilterSelect label="Volume" value={filters.volume} options={data.volumes} onChange={(v) => setFilter('volume', v)} />
      <FilterSelect label="Pick" value={filters.pick} options={data.pick_values} onChange={(v) => setFilter('pick', v)} />
      <FilterSelect label="Edit Status" value={filters.edit_status} options={data.edit_status_values} onChange={(v) => setFilter('edit_status', v)} />
      <FilterSelect label="Project" value={filters.project} options={data.projects} onChange={(v) => setFilter('project', v)} />
      <FilterSelect label="Color" value={filters.color_label} options={data.color_values} onChange={(v) => setFilter('color_label', v)} />

      {/* Rating range */}
      <div className="mb-3">
        <label className="block text-[11px] text-[var(--text-dim)] mb-1 uppercase tracking-wider">
          Min Rating
        </label>
        <div className="flex gap-1">
          {[0, 1, 2, 3, 4, 5].map((n) => (
            <button
              key={n}
              onClick={() => setFilter('rating_min', n || undefined)}
              className={`w-7 h-7 rounded text-xs ${
                filters.rating_min === n ? 'bg-[var(--accent)] text-black' : 'bg-[var(--bg3)] text-[var(--text-mid)]'
              }`}
            >
              {n}
            </button>
          ))}
        </div>
      </div>

      {/* Date range */}
      <div className="mb-3">
        <label className="block text-[11px] text-[var(--text-dim)] mb-1 uppercase tracking-wider">
          Date range
        </label>
        <div className="flex flex-col gap-1.5">
          <input
            type="date"
            value={filters.date_from || ''}
            min={data.date_min?.split('T')[0]}
            max={filters.date_to || data.date_max?.split('T')[0]}
            onChange={(e) => setFilter('date_from', e.target.value || undefined)}
            className="w-full bg-[var(--bg3)] text-[var(--text)] border border-[var(--border)] rounded px-2 py-1 text-sm date-input-dark"
          />
          <input
            type="date"
            value={filters.date_to || ''}
            min={filters.date_from || data.date_min?.split('T')[0]}
            max={data.date_max?.split('T')[0]}
            onChange={(e) => setFilter('date_to', e.target.value || undefined)}
            className="w-full bg-[var(--bg3)] text-[var(--text)] border border-[var(--border)] rounded px-2 py-1 text-sm date-input-dark"
          />
        </div>
      </div>
    </div>
  )
}
