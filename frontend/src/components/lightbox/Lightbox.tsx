import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { X, ChevronLeft, ChevronRight, Star, FolderOpen, Image as ImageIcon, ChevronDown, Search } from 'lucide-react'
import type { DamImage } from '../../types'
import { usePatchImage, useOpenExternal, useOpenJpeg, useAddKeyword, useRemoveKeyword, useAddProject, useRemoveProject } from '../../api/images'
import { useInstalledApps, useFilters } from '../../api/filters'
import { useUIStore } from '../../stores/useUIStore'

const DEFAULT_APPS: { label: string; app: string | undefined }[] = [
  { label: 'System default', app: undefined },
  { label: 'Capture One', app: 'Capture One' },
  { label: 'DxO PhotoLab', app: 'DxO PhotoLab' },
  { label: 'DxO FilmPack', app: 'DxO FilmPack' },
  { label: 'DaVinci Resolve', app: 'DaVinci Resolve' },
]

interface Props {
  image: DamImage
  images: DamImage[]
  currentIndex: number
  onClose: () => void
  onNavigate: (index: number) => void
}

export function Lightbox({ image, images, currentIndex, onClose, onNavigate }: Props) {
  const patchImage = usePatchImage()
  const openExternal = useOpenExternal()
  const openJpeg = useOpenJpeg()
  const addKeyword = useAddKeyword()
  const removeKeyword = useRemoveKeyword()
  const addProject = useAddProject()
  const removeProject = useRemoveProject()
  const { data: filtersData } = useFilters()
  const [kwInput, setKwInput] = useState('')
  const [projInput, setProjInput] = useState('')
  const { lastOpenApp, setLastOpenApp } = useUIStore()
  const [flash, setFlash] = useState<string | null>(null)
  const [openMenuVisible, setOpenMenuVisible] = useState(false)
  const [browsing, setBrowsing] = useState(false)
  const [appFilter, setAppFilter] = useState('')
  const appFilterRef = useRef<HTMLInputElement>(null)
  const { data: appsData } = useInstalledApps()

  // Filter installed apps, excluding ones already in defaults
  const defaultAppNames = useMemo(() => new Set(DEFAULT_APPS.map(d => d.app)), [])
  const filteredApps = useMemo(() => {
    const all = appsData?.apps ?? []
    const extras = all.filter(name => !defaultAppNames.has(name))
    if (!appFilter) return extras
    const q = appFilter.toLowerCase()
    return extras.filter(name => name.toLowerCase().includes(q))
  }, [appsData, appFilter, defaultAppNames])

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

  const showFlash = useCallback((msg: string) => {
    setFlash(msg)
    setTimeout(() => setFlash(null), 2000)
  }, [])

  const handleOpenExternal = useCallback((app?: string) => {
    openExternal.mutate({ id: image.id, app }, {
      onSuccess: () => showFlash(app ? `Opened in ${app}` : 'Opened in default app'),
      onError: (err) => showFlash(err.message),
    })
  }, [image.id, openExternal, showFlash])

  const handleOpenWithApp = useCallback((app: string | undefined) => {
    setLastOpenApp(app)
    setOpenMenuVisible(false)
    setBrowsing(false)
    setAppFilter('')
    handleOpenExternal(app)
  }, [handleOpenExternal, setLastOpenApp])

  const handleOpenJpeg = useCallback(() => {
    openJpeg.mutate(image.id, {
      onSuccess: () => showFlash('Opened JPEG sidecar'),
      onError: (err) => showFlash(err.message),
    })
  }, [image.id, openJpeg, showFlash])

  // Close app menu on outside click
  useEffect(() => {
    if (!openMenuVisible) return
    const close = (e: MouseEvent) => {
      // Don't close if clicking inside the menu (search input, scrolling, etc.)
      const menu = document.getElementById('open-with-menu')
      if (menu?.contains(e.target as Node)) return
      setOpenMenuVisible(false)
      setBrowsing(false)
      setAppFilter('')
    }
    window.addEventListener('mousedown', close)
    return () => window.removeEventListener('mousedown', close)
  }, [openMenuVisible])

  // Auto-focus search input when browsing
  useEffect(() => {
    if (browsing) appFilterRef.current?.focus()
  }, [browsing])

  // Preload adjacent images (N+1 and N-1)
  useEffect(() => {
    ;[images[currentIndex + 1], images[currentIndex - 1]].forEach((adj) => {
      if (adj) {
        const img = new Image()
        img.src = `/api/thumbs/${adj.id}.jpg`
      }
    })
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
        case 'o': case 'O': handleOpenExternal(lastOpenApp); break
        case 'j': case 'J': if (image.has_jpeg) handleOpenJpeg(); break
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose, goNext, goPrev, setPick, setRating, handleOpenExternal, handleOpenJpeg, image.has_jpeg, lastOpenApp])

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
          {/* Open in external app — split button */}
          <div className="relative flex items-center">
            <button onClick={() => handleOpenExternal(lastOpenApp)}
              className="text-[var(--text-dim)] hover:text-white flex items-center gap-1 text-xs"
              title={`Open in ${lastOpenApp ?? 'default app'} (O)`}>
              <FolderOpen size={15} />
              <span className="hidden sm:inline">{lastOpenApp ?? 'Open'}</span>
            </button>
            <button onClick={() => setOpenMenuVisible((v) => !v)}
              className="text-[var(--text-dim)] hover:text-white ml-0.5"
              title="Choose app">
              <ChevronDown size={12} />
            </button>
            {openMenuVisible && (
              <div id="open-with-menu" className="absolute top-full right-0 mt-1 py-1 rounded bg-[var(--bg2)] border border-[var(--border)] shadow-lg z-50 min-w-[200px]">
                {/* Quick-access defaults */}
                {DEFAULT_APPS.map(({ label, app }) => (
                  <button key={label} onClick={() => handleOpenWithApp(app)}
                    className={`w-full text-left px-3 py-1.5 text-xs hover:bg-[var(--bg3)] ${
                      lastOpenApp === app ? 'text-[var(--accent)]' : 'text-[var(--text)]'
                    }`}>
                    {label}
                  </button>
                ))}
                {/* Divider + Browse */}
                <div className="border-t border-[var(--border)] my-1" />
                {!browsing ? (
                  <button onClick={() => setBrowsing(true)}
                    className="w-full text-left px-3 py-1.5 text-xs text-[var(--text-mid)] hover:bg-[var(--bg3)]">
                    Open with...
                  </button>
                ) : (
                  <>
                    <div className="px-2 py-1">
                      <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-[var(--bg)] border border-[var(--border)]">
                        <Search size={11} className="text-[var(--text-dim)] shrink-0" />
                        <input
                          ref={appFilterRef}
                          type="text"
                          value={appFilter}
                          onChange={(e) => setAppFilter(e.target.value)}
                          placeholder="Filter apps..."
                          className="flex-1 bg-transparent text-xs outline-none text-[var(--text)] placeholder:text-[var(--text-dim)]"
                        />
                      </div>
                    </div>
                    <div className="max-h-48 overflow-y-auto">
                      {filteredApps.map((name) => (
                        <button key={name} onClick={() => handleOpenWithApp(name)}
                          className={`w-full text-left px-3 py-1.5 text-xs hover:bg-[var(--bg3)] ${
                            lastOpenApp === name ? 'text-[var(--accent)]' : 'text-[var(--text)]'
                          }`}>
                          {name}
                        </button>
                      ))}
                      {filteredApps.length === 0 && (
                        <div className="px-3 py-1.5 text-xs text-[var(--text-dim)]">No matches</div>
                      )}
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
          {/* Open JPEG sidecar */}
          {image.has_jpeg && (
            <button onClick={handleOpenJpeg}
              className="text-[var(--text-dim)] hover:text-white flex items-center gap-1 text-xs"
              title="Open JPEG sidecar (J)">
              <ImageIcon size={15} />
            </button>
          )}
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

      {/* Flash notification */}
      {flash && (
        <div className="absolute top-14 left-1/2 -translate-x-1/2 px-4 py-1.5 rounded bg-[var(--bg3)] text-xs text-[var(--text)] z-50 animate-fade-in">
          {flash}
        </div>
      )}

      {/* Bottom info bar */}
      <div className="px-4 py-2 bg-black/50 space-y-1.5" onClick={(e) => e.stopPropagation()}>
        <div className="text-xs text-[var(--text-mid)]">{exifLine}</div>
        {image.ai_description && (
          <div className="text-xs text-[var(--text-dim)] italic">{image.ai_description}</div>
        )}
        {/* Editable keywords */}
        <div className="flex gap-1 flex-wrap items-center">
          <span className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider mr-1">Keywords</span>
          {image.keywords.map((kw) => (
            <span key={kw} className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--bg3)] text-[var(--text-mid)] flex items-center gap-1 group">
              {kw}
              <button onClick={() => removeKeyword.mutate({ id: image.id, keyword: kw })}
                className="text-[var(--text-dim)] hover:text-[var(--reject)] opacity-0 group-hover:opacity-100 transition-opacity">
                <X size={10} />
              </button>
            </span>
          ))}
          <input
            type="text"
            value={kwInput}
            onChange={(e) => setKwInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && kwInput.trim()) {
                addKeyword.mutate({ id: image.id, keyword: kwInput.trim().toLowerCase() })
                setKwInput('')
                e.stopPropagation()
              }
            }}
            placeholder="+ keyword"
            className="text-[10px] bg-transparent border-b border-[var(--border)] text-[var(--text-mid)] outline-none w-20 placeholder:text-[var(--text-dim)]"
          />
        </div>
        {/* Editable projects */}
        <div className="flex gap-1 flex-wrap items-center">
          <span className="text-[10px] text-[var(--text-dim)] uppercase tracking-wider mr-1">Projects</span>
          {image.projects.map((p) => (
            <span key={p} className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--accent)]/20 text-[var(--accent)] flex items-center gap-1 group">
              {p}
              <button onClick={() => removeProject.mutate({ id: image.id, name: p })}
                className="text-[var(--accent)] hover:text-[var(--reject)] opacity-0 group-hover:opacity-100 transition-opacity">
                <X size={10} />
              </button>
            </span>
          ))}
          <input
            type="text"
            value={projInput}
            onChange={(e) => setProjInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && projInput.trim()) {
                addProject.mutate({ id: image.id, name: projInput.trim() })
                setProjInput('')
                e.stopPropagation()
              }
            }}
            placeholder="+ project"
            list="project-suggestions"
            className="text-[10px] bg-transparent border-b border-[var(--border)] text-[var(--text-mid)] outline-none w-20 placeholder:text-[var(--text-dim)]"
          />
          <datalist id="project-suggestions">
            {filtersData?.projects.map((p) => <option key={p} value={p} />)}
          </datalist>
        </div>
      </div>
    </div>
  )
}
