import { ChevronDown, ChevronUp } from 'lucide-react'
import { useIngestStatus, useTagStatus } from '../../api/ingest'
import { useUIStore } from '../../stores/useUIStore'

const PHASES = ['Copy', 'Scan', 'Thumbs', 'Tag'] as const

function phaseIndex(ingestStatus: string, taggerStatus: string): number {
  if (taggerStatus === 'tagging') return 3
  if (ingestStatus === 'thumbs') return 2
  if (ingestStatus === 'scanning_db') return 1
  if (ingestStatus === 'copying') return 0
  return -1
}

function PhasePill({ label, state }: { label: string; state: 'done' | 'active' | 'pending' }) {
  const base = 'px-2 py-0.5 rounded text-[10px] font-medium'
  if (state === 'active') return <span className={`${base} bg-[var(--accent)] text-black`}>{label}</span>
  if (state === 'done') return <span className={`${base} bg-[var(--bg3)] text-[var(--accent)]`}>{label}</span>
  return <span className={`${base} bg-[var(--bg3)] text-[var(--text-dim)]`}>{label}</span>
}

export function IngestMonitor() {
  const { data: ingest } = useIngestStatus()
  const { data: tagger } = useTagStatus()
  const { ingestMonitorCollapsed, toggleIngestMonitor, addToast } = useUIStore()

  const ingestS = ingest?.status ?? 'idle'
  const taggerS = tagger?.status ?? 'idle'

  const isActive = ingestS !== 'idle' || taggerS === 'tagging' || taggerS === 'done'
  if (!isActive) return null

  const active = phaseIndex(ingestS, taggerS)
  const current = taggerS === 'tagging' ? (tagger?.current ?? 0) : (ingest?.current ?? 0)
  const total = taggerS === 'tagging' ? (tagger?.total ?? 0) : (ingest?.total ?? 0)
  const pct = total > 0 ? Math.round((current / total) * 100) : 0
  const keywords = tagger?.last_keywords ?? []
  const logPath = '~/Documents/dam/card_watcher.log'

  const thumbSrc = (() => {
    if (taggerS === 'tagging' && tagger?.current_id) return `/api/thumbs/${tagger.current_id}.jpg`
    if (ingestS === 'copying') return '/api/ingest/preview'
    return null
  })()

  const handleLogClick = () => {
    try {
      ;(window as any).pywebview?.api?.open_path?.(logPath)
    } catch {
      navigator.clipboard.writeText(logPath).then(() => {
        addToast('Log path copied to clipboard', 'info')
      }).catch(() => {
        addToast('Could not copy log path', 'error')
      })
    }
  }

  return (
    <div className="border-b border-[var(--border)] bg-[var(--bg2)] shrink-0">
      {ingestMonitorCollapsed ? (
        <div
          className="flex items-center gap-3 px-3 h-7 cursor-pointer hover:bg-[var(--bg3)]"
          onClick={toggleIngestMonitor}
        >
          <span className="text-[11px] text-[var(--text-mid)]">
            {active >= 0 ? PHASES[active] : 'Starting'}
          </span>
          <div className="flex-1 h-1 rounded bg-[var(--bg)] overflow-hidden">
            <div
              className="h-full bg-[var(--accent)] transition-all duration-300"
              style={{ width: `${pct}%` }}
            />
          </div>
          <span className="text-[11px] text-[var(--text-dim)]">{current}/{total}</span>
          <ChevronDown size={12} className="text-[var(--text-dim)]" />
        </div>
      ) : (
        <div className="px-3 py-2 space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              {PHASES.map((label, i) => (
                <PhasePill
                  key={label}
                  label={label}
                  state={i === active ? 'active' : i < active ? 'done' : 'pending'}
                />
              ))}
            </div>
            <button onClick={toggleIngestMonitor} className="text-[var(--text-dim)] hover:text-[var(--text)]">
              <ChevronUp size={14} />
            </button>
          </div>

          <div className="flex items-start gap-3">
            {thumbSrc && (
              <img
                key={thumbSrc === '/api/ingest/preview' ? ingest?.current_path : tagger?.current_id}
                src={thumbSrc}
                alt=""
                className="w-20 h-[54px] object-cover rounded bg-[var(--bg3)] shrink-0"
              />
            )}
            <div className="flex-1 min-w-0">
              <p className="text-[12px] text-[var(--text)]">
                {total > 0 ? `${current} / ${total} photos` : 'Starting…'}
              </p>
              {keywords.length > 0 && (
                <p className="text-[11px] text-[var(--text-dim)] truncate mt-0.5">
                  {keywords.join(' · ')}
                </p>
              )}
            </div>
          </div>

          <div className="h-1.5 rounded bg-[var(--bg)] overflow-hidden">
            <div
              className="h-full bg-[var(--accent)] transition-all duration-300"
              style={{ width: `${pct}%` }}
            />
          </div>

          <div className="flex items-center justify-between">
            <span className="text-[10px] text-[var(--text-dim)]">{logPath}</span>
            <button
              onClick={handleLogClick}
              className="text-[10px] text-[var(--accent)] hover:underline"
            >
              {(window as any).pywebview ? 'Open in Finder' : 'Copy path'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
