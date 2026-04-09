import { useRef, useCallback, useEffect } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import type { DamImage } from '../../types'
import { useUIStore } from '../../stores/useUIStore'
import { usePatchImage } from '../../api/images'
import { StarRating } from '../shared/StarRating'

interface Props {
  images: DamImage[]
  hasNextPage: boolean
  isFetchingNextPage: boolean
  fetchNextPage: () => void
}

const PICK_LABEL: Record<string, { label: string; cls: string }> = {
  pick: { label: 'Pick', cls: 'text-[var(--pick)] border-[var(--pick)]/40' },
  reject: { label: 'Rej', cls: 'text-[var(--reject)] border-[var(--reject)]/40' },
  unmarked: { label: '—', cls: 'text-[var(--text-dim)] border-[var(--border)]' },
}

const ROW_H = 52

export function ImageList({ images, hasNextPage, isFetchingNextPage, fetchNextPage }: Props) {
  const parentRef = useRef<HTMLDivElement>(null)
  const { selectedIds, selectAll, openLightbox, rangeSelect, lastClickedIndex, select, lightboxIndex } = useUIStore()
  const patchImage = usePatchImage()

  // Cmd+A
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (lightboxIndex !== null) return
      if ((e.metaKey || e.ctrlKey) && e.key === 'a') {
        e.preventDefault()
        selectAll(images)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [images, selectAll, lightboxIndex])

  const virtualizer = useVirtualizer({
    count: images.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_H,
    overscan: 10,
  })

  const handleScroll = useCallback(() => {
    const el = parentRef.current
    if (!el || isFetchingNextPage || !hasNextPage) return
    const { scrollTop, scrollHeight, clientHeight } = el
    if (scrollHeight - scrollTop - clientHeight < ROW_H * 5) {
      fetchNextPage()
    }
  }, [isFetchingNextPage, hasNextPage, fetchNextPage])

  const handleRowClick = useCallback(
    (img: DamImage, index: number, e: React.MouseEvent) => {
      if (e.shiftKey && lastClickedIndex !== null) {
        rangeSelect(lastClickedIndex, index, images)
      } else if (e.metaKey || e.ctrlKey) {
        const next = new Set(selectedIds)
        if (next.has(img.id)) next.delete(img.id)
        else next.add(img.id)
        useUIStore.setState({ selectedIds: next, selectedId: img.id })
      } else {
        select(img.id, index)
        openLightbox(index)
      }
    },
    [images, lastClickedIndex, rangeSelect, selectedIds, select, openLightbox]
  )

  return (
    <div ref={parentRef} onScroll={handleScroll} className="h-full overflow-auto">
      {/* Header */}
      <div className="sticky top-0 z-10 flex items-center px-3 py-1.5 bg-[var(--bg2)] border-b border-[var(--border)] text-[10px] text-[var(--text-dim)] uppercase tracking-wider">
        <div className="w-16 shrink-0" />
        <div className="flex-1 min-w-0">Filename</div>
        <div className="w-[120px] shrink-0">Date</div>
        <div className="w-[90px] shrink-0">Camera</div>
        <div className="w-[110px] shrink-0">Rating</div>
        <div className="w-[60px] shrink-0">Pick</div>
        <div className="w-[160px] shrink-0">Keywords</div>
      </div>

      <div style={{ height: virtualizer.getTotalSize(), width: '100%', position: 'relative' }}>
        {virtualizer.getVirtualItems().map((vRow) => {
          const img = images[vRow.index]
          if (!img) return null
          const isSelected = selectedIds.has(img.id)
          const pick = PICK_LABEL[img.pick] ?? PICK_LABEL.unmarked

          return (
            <div
              key={vRow.key}
              style={{ position: 'absolute', top: vRow.start, left: 0, width: '100%', height: ROW_H }}
              onClick={(e) => handleRowClick(img, vRow.index, e)}
              className={`flex items-center px-3 gap-3 border-b border-[var(--border)] cursor-pointer select-none
                ${isSelected ? 'bg-[var(--accent)]/10' : 'hover:bg-[var(--bg2)]'}
              `}
            >
              {/* Thumbnail */}
              <div className="w-16 shrink-0 h-[40px] rounded overflow-hidden bg-[var(--bg3)]">
                <img
                  src={`/api/thumbs/${img.id}.jpg`}
                  alt=""
                  className="w-full h-full object-cover"
                  loading="lazy"
                />
              </div>

              {/* Filename */}
              <div className="flex-1 min-w-0">
                <div className="text-xs truncate text-[var(--text)]">{img.file_name}</div>
                {img.ai_description && (
                  <div className="text-[10px] text-[var(--text-dim)] truncate">{img.ai_description}</div>
                )}
              </div>

              {/* Date */}
              <div className="w-[120px] shrink-0 text-[11px] text-[var(--text-dim)]">
                {img.date_taken ? img.date_taken.slice(0, 10) : '—'}
              </div>

              {/* Camera */}
              <div className="w-[90px] shrink-0 text-[11px] text-[var(--text-dim)] truncate">
                {img.camera_short ?? '—'}
              </div>

              {/* Rating */}
              <div className="w-[110px] shrink-0" onClick={(e) => e.stopPropagation()}>
                <StarRating
                  value={img.rating}
                  size="sm"
                  onChange={(r) => patchImage.mutate({ id: img.id, patch: { rating: r } })}
                />
              </div>

              {/* Pick */}
              <div className="w-[60px] shrink-0">
                <span className={`text-[10px] font-medium border rounded px-1.5 py-0.5 ${pick.cls}`}>
                  {pick.label}
                </span>
              </div>

              {/* Keywords */}
              <div className="w-[160px] shrink-0 text-[10px] text-[var(--text-dim)] truncate">
                {img.keywords?.join(', ') ?? ''}
              </div>
            </div>
          )
        })}
      </div>

      {isFetchingNextPage && (
        <div className="text-center py-4 text-[var(--text-dim)] text-sm">Loading more...</div>
      )}
    </div>
  )
}
