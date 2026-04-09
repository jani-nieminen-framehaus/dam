import { X, AlertCircle, AlertTriangle, Info, CheckCircle } from 'lucide-react'
import { useUIStore } from '../../stores/useUIStore'
import type { ToastType } from '../../stores/useUIStore'

const ICONS: Record<ToastType, React.ComponentType<{ size?: number; className?: string }>> = {
  error: AlertCircle,
  warning: AlertTriangle,
  info: Info,
  success: CheckCircle,
}

const COLORS: Record<ToastType, string> = {
  error: 'border-red-500/50 bg-red-950/80 text-red-200',
  warning: 'border-yellow-500/50 bg-yellow-950/80 text-yellow-200',
  info: 'border-blue-500/50 bg-blue-950/80 text-blue-200',
  success: 'border-green-500/50 bg-green-950/80 text-green-200',
}

export function ToastContainer() {
  const { toasts, dismissToast } = useUIStore()

  if (toasts.length === 0) return null

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm">
      {toasts.map((toast) => {
        const Icon = ICONS[toast.type]
        return (
          <div
            key={toast.id}
            className={`flex items-start gap-3 px-4 py-3 rounded border backdrop-blur-sm ${COLORS[toast.type]}`}
          >
            <Icon size={16} className="mt-0.5 shrink-0" />
            <span className="text-sm flex-1">{toast.message}</span>
            <button
              onClick={() => dismissToast(toast.id)}
              className="opacity-60 hover:opacity-100 transition-opacity shrink-0"
            >
              <X size={14} />
            </button>
          </div>
        )
      })}
    </div>
  )
}
