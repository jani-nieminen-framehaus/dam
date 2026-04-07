import { PanelLeftClose, PanelLeft, Minus, Plus } from 'lucide-react'
import { useUIStore } from '../../stores/useUIStore'

interface Props {
  totalFiltered: number
}

export function Toolbar({ totalFiltered }: Props) {
  const { sidebarOpen, toggleSidebar, thumbSize, setThumbSize } = useUIStore()

  return (
    <div className="h-11 flex items-center px-3 gap-3 border-b border-[var(--border)] bg-[var(--bg2)] shrink-0">
      <button onClick={toggleSidebar} className="hover:text-[var(--accent)] transition-colors" title="Toggle sidebar">
        {sidebarOpen ? <PanelLeftClose size={18} /> : <PanelLeft size={18} />}
      </button>

      <span className="text-sm font-bold">DAM</span>

      <div className="flex-1" />

      <span className="text-xs text-[var(--text-dim)]">
        {totalFiltered.toLocaleString()} images
      </span>

      {/* Thumbnail size slider */}
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
    </div>
  )
}
