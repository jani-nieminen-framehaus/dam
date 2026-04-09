import { useEffect } from 'react'

interface Props {
  onClose: () => void
}

const GRID_SHORTCUTS = [
  ['Click', 'Select image'],
  ['Shift+Click', 'Range select'],
  ['Cmd/Ctrl+Click', 'Toggle select'],
  ['Cmd/Ctrl+A', 'Select all visible'],
  ['Double-click', 'Open lightbox'],
]

const LIGHTBOX_SHORTCUTS = [
  ['← / →', 'Previous / next image'],
  ['P', 'Pick (auto-advance)'],
  ['R', 'Reject (auto-advance)'],
  ['U', 'Reset pick/reject'],
  ['0–5', 'Set rating (0 clears)'],
  ['O', 'Open in external app'],
  ['J', 'Open JPEG sidecar'],
  ['Esc', 'Close lightbox'],
]

const GLOBAL_SHORTCUTS = [
  ['?', 'Toggle this help'],
]

export function KeyboardHelp({ onClose }: Props) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70" onClick={onClose}>
      <div className="bg-[var(--bg2)] border border-[var(--border)] rounded-lg p-6 max-w-lg w-full mx-4"
        onClick={(e) => e.stopPropagation()}>
        <h2 className="text-sm font-bold mb-4 text-[var(--text)]">Keyboard Shortcuts</h2>

        <div className="grid grid-cols-2 gap-6">
          <div>
            <h3 className="text-[11px] uppercase tracking-wider text-[var(--text-dim)] mb-2">Grid</h3>
            {GRID_SHORTCUTS.map(([key, desc]) => (
              <div key={key} className="flex justify-between text-xs mb-1.5">
                <kbd className="text-[var(--accent)] font-mono">{key}</kbd>
                <span className="text-[var(--text-mid)]">{desc}</span>
              </div>
            ))}
          </div>

          <div>
            <h3 className="text-[11px] uppercase tracking-wider text-[var(--text-dim)] mb-2">Lightbox</h3>
            {LIGHTBOX_SHORTCUTS.map(([key, desc]) => (
              <div key={key} className="flex justify-between text-xs mb-1.5">
                <kbd className="text-[var(--accent)] font-mono">{key}</kbd>
                <span className="text-[var(--text-mid)]">{desc}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-4 pt-3 border-t border-[var(--border)]">
          {GLOBAL_SHORTCUTS.map(([key, desc]) => (
            <div key={key} className="flex justify-between text-xs">
              <kbd className="text-[var(--accent)] font-mono">{key}</kbd>
              <span className="text-[var(--text-mid)]">{desc}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
