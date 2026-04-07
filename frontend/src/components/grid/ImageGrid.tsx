import { useRef, useCallback, useMemo, useEffect } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import type { DamImage } from '../../types'
import { ImageCard } from './ImageCard'

interface Props {
  images: DamImage[]
  thumbSize: number
  hasNextPage: boolean
  isFetchingNextPage: boolean
  fetchNextPage: () => void
}

export function ImageGrid({ images, thumbSize, hasNextPage, isFetchingNextPage, fetchNextPage }: Props) {
  const parentRef = useRef<HTMLDivElement>(null)
  const gap = 4

  // Calculate columns based on container width
  const columns = useMemo(() => {
    if (!parentRef.current) return 6
    const w = parentRef.current.clientWidth
    return Math.max(1, Math.floor((w + gap) / (thumbSize + gap)))
  }, [thumbSize])

  const rowCount = Math.ceil(images.length / columns)

  const virtualizer = useVirtualizer({
    count: rowCount,
    getScrollElement: () => parentRef.current,
    estimateSize: () => thumbSize + gap,
    overscan: 3,
  })

  // Infinite scroll: fetch more when near bottom
  const handleScroll = useCallback(() => {
    const el = parentRef.current
    if (!el || isFetchingNextPage || !hasNextPage) return
    const { scrollTop, scrollHeight, clientHeight } = el
    if (scrollHeight - scrollTop - clientHeight < thumbSize * 3) {
      fetchNextPage()
    }
  }, [isFetchingNextPage, hasNextPage, fetchNextPage, thumbSize])

  // Recalculate columns on resize
  useEffect(() => {
    const el = parentRef.current
    if (!el) return
    const ro = new ResizeObserver(() => virtualizer.measure())
    ro.observe(el)
    return () => ro.disconnect()
  }, [virtualizer])

  return (
    <div
      ref={parentRef}
      onScroll={handleScroll}
      className="h-full overflow-auto p-2"
    >
      <div
        style={{
          height: virtualizer.getTotalSize(),
          width: '100%',
          position: 'relative',
        }}
      >
        {virtualizer.getVirtualItems().map((virtualRow) => {
          const startIdx = virtualRow.index * columns
          const rowImages = images.slice(startIdx, startIdx + columns)

          return (
            <div
              key={virtualRow.key}
              style={{
                position: 'absolute',
                top: virtualRow.start,
                left: 0,
                width: '100%',
                height: virtualRow.size,
                display: 'flex',
                gap,
              }}
            >
              {rowImages.map((img) => (
                <ImageCard key={img.id} image={img} size={thumbSize} />
              ))}
            </div>
          )
        })}
      </div>

      {isFetchingNextPage && (
        <div className="text-center py-4 text-[var(--text-dim)]">Loading more...</div>
      )}
    </div>
  )
}
