import { useCallback, useEffect, useRef } from 'react'
import { X, ChevronLeft, ChevronRight, Star } from 'lucide-react'
import type { DamImage } from '../../types'
import { usePatchImage } from '../../api/images'

interface Props {
  image: DamImage
  images: DamImage[]
  currentIndex: number
  onClose: () => void
  onNavigate: (index: number) => void
}

export function Lightbox({ image, images, currentIndex, onClose, onNavigate }: Props) {
  const patchImage = usePatchImage()
  const preloadRef = useRef<HTMLImageElement | null>(null)

  const canPrev = currentIndex > 0
  const canNext = currentIndex < images.length - 1

  const goNext = useCallback(() => {
    if (canNext) onNavigate(currentIndex + 1)
  }, [canNext, currentIndex, onNavigate])

  const goPrev = useCallback(() => {
    if (canPrev) onNavigate(currentIndex - 1)
  }, [canPrev, currentIndex, onNavigate])

  // Auto-advance after pick/reject
  const patchAndAdvance = useCallback((patch: Partial<DamImage>) => {
    patchImage.mutate({ id: image.id, patch })
    if (canNext) setTimeout(goNext, 80) // Tiny delay for visual feedback
  }, [image.id, patchImage, canNext, goNext])

  const setPick = useCallback((pick: 'pick' | 'reject' | 'unmarked') => {
    if (pick === 'unmarked') {
      patchImage.mutate({ id: image.id, patch: { pick } })
    } else {
      patchAndAdvance({ pick })
    }
  }, [image.id, patchImage, patchAndAdvance])

  const setRating = useCallback((rating: number) => {
    patchImage.mutate({ id: image.id, patch: { rating } })
  }, [image.id, patchImage])

  // Preload adjacent images
  useEffect(() => {
    const nextImg = images[currentIndex + 1]
    if (nextImg) {
      const img = new Image()
      img.src = `/api/thumbs/${nextImg.id}.jpg`
      preloadRef.current = img
    }
  }, [currentIndex, images])

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
      switch (e.key) {
        case 'Escape': onClose(); break
        case 'ArrowRight': goNext(); break
        case 'ArrowLeft': goPrev(); break
        case 'p': case 'P': setPick('pick'); break
        case 'r': case 'R': setPick('reject'); break
        case 'u': case 'U': setPick('unmarked'); break
        case '0': setRating(0); break
        case '1': setRating(1); break
        case '2': setRating(2); break
        case '3': setRating(3); break
        case '4': setRating(4); break
        case '5': setRating(5); break
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose, goNext, goPrev, setPick, setRating])

  const exifLine = [
    image.camera_short,
    image.lens_model,
    image.focal_length ? `${image.focal_length}mm` : null,
    image.aperture ? `f/${image.aperture}` : null,
    image.shutter_speed,
    image.iso ? `ISO ${image.iso}` : null,
  ].filter(Boolean).join('  ·  ')

  return (
    <div className="fixed inset-0 z-50 bg-black/95 flex flex-col" onClick={onClose}>
      {/* Top bar */}
      <div className="flex items-center justify-between px-4 py-2 bg-black/50" onClick={(e) => e.stopPropagation()}>
        <div className="text-sm text-[var(--text-mid)]">
          {image.file_name} — {currentIndex + 1} / {images.length}
        </div>
        <div className="flex items-center gap-3">
          {/* Pick/Reject buttons */}
          <button onClick={() => setPick('pick')}
            className={`px-2 py-0.5 rounded text-xs font-bold ${image.pick === 'pick' ? 'bg-[var(--pick)] text-black' : 'text-[var(--text-dim)] hover:text-[var(--pick)]'}`}>
            P Pick
          </button>
          <button onClick={() => setPick('reject')}
            className={`px-2 py-0.5 rounded text-xs font-bold ${image.pick === 'reject' ? 'bg-[var(--reject)] text-white' : 'text-[var(--text-dim)] hover:text-[var(--reject)]'}`}>
            R Reject
          </button>
          <button onClick={() => setPick('unmarked')}
            className={`px-2 py-0.5 rounded text-xs ${image.pick === 'unmarked' ? 'text-white' : 'text-[var(--text-dim)]'}`}>
            U Reset
          </button>
          <div className="w-px h-4 bg-[var(--border)]" />
          {/* Star rating */}
          <div className="flex gap-0.5">
            {[1, 2, 3, 4, 5].map((n) => (
              <button key={n} onClick={() => setRating(image.rating === n ? 0 : n)}>
                <Star size={16} fill={n <= image.rating ? 'var(--accent)' : 'none'}
                  stroke={n <= image.rating ? 'var(--accent)' : 'var(--text-dim)'} />
              </button>
            ))}
          </div>
          <div className="w-px h-4 bg-[var(--border)]" />
          <button onClick={onClose} className="text-[var(--text-dim)] hover:text-white">
            <X size={18} />
          </button>
        </div>
      </div>

      {/* Main image area */}
      <div className="flex-1 flex items-center justify-center relative min-h-0" onClick={(e) => e.stopPropagation()}>
        {canPrev && (
          <button onClick={goPrev} className="absolute left-4 text-white/40 hover:text-white z-10">
            <ChevronLeft size={40} />
          </button>
        )}

        <img
          src={`/api/thumbs/${image.id}.jpg`}
          alt={image.file_name}
          className="max-h-full max-w-full object-contain"
        />

        {canNext && (
          <button onClick={goNext} className="absolute right-4 text-white/40 hover:text-white z-10">
            <ChevronRight size={40} />
          </button>
        )}
      </div>

      {/* Bottom info bar */}
      <div className="px-4 py-2 bg-black/50 space-y-1" onClick={(e) => e.stopPropagation()}>
        <div className="text-xs text-[var(--text-mid)]">{exifLine}</div>
        {image.ai_description && (
          <div className="text-xs text-[var(--text-dim)] italic">{image.ai_description}</div>
        )}
        {image.keywords.length > 0 && (
          <div className="flex gap-1 flex-wrap">
            {image.keywords.map((kw) => (
              <span key={kw} className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--bg3)] text-[var(--text-mid)]">
                {kw}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
