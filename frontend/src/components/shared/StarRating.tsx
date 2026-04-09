import { Star } from 'lucide-react'

interface Props {
  value: number
  onChange?: (rating: number) => void
  size?: 'sm' | 'md'
  readonly?: boolean
}

const PX = { sm: 13, md: 16 }

export function StarRating({ value, onChange, size = 'md', readonly = false }: Props) {
  const px = PX[size]
  return (
    <div className="flex gap-0.5">
      {[1, 2, 3, 4, 5].map((n) => (
        <button
          key={n}
          onClick={readonly ? undefined : () => onChange?.(value === n ? 0 : n)}
          disabled={readonly}
          className={readonly ? 'cursor-default' : 'hover:scale-110 transition-transform'}
          tabIndex={readonly ? -1 : 0}
        >
          <Star
            size={px}
            fill={n <= value ? 'var(--accent)' : 'none'}
            stroke={n <= value ? 'var(--accent)' : 'var(--text-dim)'}
          />
        </button>
      ))}
    </div>
  )
}
