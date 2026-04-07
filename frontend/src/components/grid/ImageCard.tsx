import { Star } from 'lucide-react'
import type { DamImage } from '../../types'
import { useUIStore } from '../../stores/useUIStore'

interface Props {
  image: DamImage
  size: number
}

export function ImageCard({ image, size }: Props) {
  const { selectedId, select, toggleSelect } = useUIStore()
  const isSelected = selectedId === image.id

  const handleClick = (e: React.MouseEvent) => {
    if (e.metaKey || e.ctrlKey) {
      toggleSelect(image.id)
    } else {
      select(image.id)
    }
  }

  return (
    <div
      onClick={handleClick}
      className="relative cursor-pointer group"
      style={{ width: size, height: size }}
    >
      {/* Selection ring */}
      <div className={`absolute inset-0 rounded border-2 z-10 pointer-events-none transition-colors ${
        isSelected ? 'border-[var(--sel)]' : 'border-transparent group-hover:border-[var(--border)]'
      }`} />

      {/* Thumbnail */}
      <img
        src={`/api/thumbs/${image.id}.jpg`}
        alt={image.file_name}
        loading="lazy"
        className="w-full h-full object-cover rounded bg-[var(--bg2)]"
      />

      {/* Pick badge */}
      {image.pick !== 'unmarked' && (
        <div className={`absolute top-1 left-1 text-xs font-bold px-1 rounded ${
          image.pick === 'pick' ? 'bg-[var(--pick)] text-black' : 'bg-[var(--reject)] text-white'
        }`}>
          {image.pick === 'pick' ? 'P' : 'R'}
        </div>
      )}

      {/* Rating stars */}
      {image.rating > 0 && (
        <div className="absolute bottom-1 left-1 flex gap-0.5">
          {Array.from({ length: image.rating }, (_, i) => (
            <Star key={i} size={10} fill="var(--accent)" stroke="none" />
          ))}
        </div>
      )}

      {/* Camera badge */}
      <div className="absolute bottom-1 right-1 text-[10px] text-[var(--text-dim)] opacity-0 group-hover:opacity-100 transition-opacity">
        {image.camera_short || ''}
      </div>
    </div>
  )
}
