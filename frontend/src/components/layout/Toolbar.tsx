import { useRef, useState, useEffect } from 'react'
import { PanelLeftClose, PanelLeft, Minus, Plus, Search, X, ArrowUpDown, LayoutGrid, List } from 'lucide-react'
import { useUIStore } from '../../stores/useUIStore'

interface Props {
  totalFiltered: number
}

export function Toolbar({ totalFiltered }: Props) {
  const { sidebarOpen, toggleSidebar, thumbSize, setThumbSize, searchQuery, setSearchQuery, clearSearch, sortBy, sortDir, setSortBy, toggleSortDir, viewMode, setViewMode } = useUIStore()
  const [inputValue, setInputValue] = useState(searchQuery)
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const isSearching = searchQuery.length > 0

  // Debounce search input
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setSearchQuery(inputValue.trim())
    }, 400)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [inputValue, setSearchQuery])

  const handleClear = () => {
    setInputValue('')
    clearSearch()
    inputRef.current?.focus()
  }

  return (
    <div className="h-11 flex items-center px-3 gap-3 border-b border-[var(--border)] bg-[var(--bg2)] shrink-0">
      {!isSearching && (
        <button data-sidebar-toggle onClick={toggleSidebar} className="hover:text-[var(--accent)] transition-colors" title="Toggle sidebar">
          {sidebarOpen ? <PanelLeftClose size={18} /> : <PanelLeft size={18} />}
        </button>
      )}

      <span className="text-sm font-bold">DAM</span>

      {/* Search bar */}
      <div className="flex items-center gap-2 flex-1 max-w-md">
        <div className="flex items-center gap-1.5 flex-1 px-2 py-1 rounded bg-[var(--bg)] border border-[var(--border)] focus-within:border-[var(--accent)] transition-colors">
          <Search size={14} className="text-[var(--text-dim)] shrink-0" />
          <input
            ref={inputRef}
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder="Search images..."
            className="flex-1 bg-transparent text-sm outline-none text-[var(--text)] placeholder:text-[var(--text-dim)]"
          />
          {inputValue && (
            <button onClick={handleClear} className="text-[var(--text-dim)] hover:text-white">
              <X size={14} />
            </button>
          )}
        </div>
        {isSearching && (
          <button
            onClick={handleClear}
            className="px-3 py-1 rounded text-xs font-medium bg-[var(--accent)] text-black hover:opacity-90 shrink-0"
          >
            Clear search
          </button>
        )}
      </div>

      <div className="flex-1" />

      {/* Sort selector */}
      <div className="flex items-center gap-1">
        <ArrowUpDown size={12} className="text-[var(--text-dim)]" />
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value)}
          className="bg-[var(--bg3)] text-[var(--text)] border border-[var(--border)] rounded px-1.5 py-0.5 text-[11px]"
        >
          <option value="date_taken">Date</option>
          <option value="rating">Rating</option>
          <option value="file_name">Name</option>
          <option value="camera_short">Camera</option>
        </select>
        <button onClick={toggleSortDir} className="text-[11px] text-[var(--text-dim)] hover:text-white w-4">
          {sortDir === 'desc' ? '↓' : '↑'}
        </button>
      </div>

      <span className="text-xs text-[var(--text-dim)]">
        {totalFiltered.toLocaleString()} images
      </span>

      {/* View mode toggle */}
      <div className="flex items-center gap-0.5 border border-[var(--border)] rounded p-0.5">
        <button
          onClick={() => setViewMode('grid')}
          className={`p-1 rounded transition-colors ${viewMode === 'grid' ? 'bg-[var(--accent)] text-black' : 'text-[var(--text-dim)] hover:text-white'}`}
          title="Grid view"
        >
          <LayoutGrid size={14} />
        </button>
        <button
          onClick={() => setViewMode('list')}
          className={`p-1 rounded transition-colors ${viewMode === 'list' ? 'bg-[var(--accent)] text-black' : 'text-[var(--text-dim)] hover:text-white'}`}
          title="List view"
        >
          <List size={14} />
        </button>
      </div>

      {/* Thumbnail size slider — grid only */}
      {viewMode === 'grid' && (
        <div className="flex items-center gap-1.5">
          <Minus size={12} className="text-[var(--text-dim)]" />
          <input
            type="range"
            min={100}
            max={400}
            step={25}
            value={thumbSize}
            onChange={(e) => setThumbSize(Number(e.target.value))}
            className="w-20 accent-[var(--accent)]"
          />
          <Plus size={12} className="text-[var(--text-dim)]" />
        </div>
      )}
    </div>
  )
}
