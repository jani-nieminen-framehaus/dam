import { useEffect, useMemo } from 'react'
import { Search, SlidersHorizontal, Camera } from 'lucide-react'
import { useImages } from './api/images'
import { useSearch } from './api/search'
import { useUIStore } from './stores/useUIStore'
import { Toolbar } from './components/layout/Toolbar'
import { StatusBar } from './components/layout/StatusBar'
import { IngestMonitor } from './components/layout/IngestMonitor'
import { FilterPanel } from './components/filters/FilterPanel'
import { ImageGrid } from './components/grid/ImageGrid'
import { ImageList } from './components/list/ImageList'
import { Lightbox } from './components/lightbox/Lightbox'
import { KeyboardHelp } from './components/shared/KeyboardHelp'
import { ToastContainer } from './components/shared/Toast'

export default function App() {
  const { filters, sidebarOpen, searchQuery, sortBy, sortDir, thumbSize, viewMode, lightboxIndex, helpOpen, toggleHelp, clearFilters, closeLightbox, setLightboxIndex } = useUIStore()
  const isSearching = searchQuery.length > 0

  // Merge sort into filters for the query key
  const feedFilters = useMemo(
    () => ({ ...filters, sort_by: sortBy, sort_dir: sortDir }),
    [filters, sortBy, sortDir]
  )

  const feed = useImages(feedFilters)
  const search = useSearch(searchQuery)

  const feedImages = useMemo(
    () => feed.data?.pages.flatMap((p) => p.images) ?? [],
    [feed.data]
  )
  const searchImages = useMemo(
    () => search.data?.images ?? [],
    [search.data]
  )

  const images = isSearching ? searchImages : feedImages
  const totalFiltered = isSearching
    ? (search.data?.total_filtered ?? 0)
    : (feed.data?.pages[0]?.total_filtered ?? 0)
  const isLoading = isSearching ? search.isLoading : feed.isLoading
  const isError = isSearching ? search.isError : feed.isError
  const error = isSearching ? search.error : feed.error

  // Update window title (works in browser tab AND pywebview)
  useEffect(() => {
    const activeFilters = Object.entries(filters).filter(([, v]) => v !== undefined)
    const parts = [`${totalFiltered.toLocaleString()} images`]
    if (isSearching) parts.push(`search: "${searchQuery}"`)
    else if (activeFilters.length > 0) parts.push(activeFilters.map(([k, v]) => `${k}: ${v}`).join(' | '))
    const title = `DAM — ${parts.join(' — ')}`
    document.title = title
    try { (window as any).pywebview?.api?.set_title(title) } catch {}
  }, [totalFiltered, filters, isSearching, searchQuery])

  // Global ? key for help overlay
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
      if (e.key === '?' || (e.shiftKey && e.key === '/')) {
        e.preventDefault()
        toggleHelp()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [toggleHelp])

  return (
  <>
    <div className="h-full flex flex-col">
      <Toolbar totalFiltered={totalFiltered} />
      <IngestMonitor />

      <div className="flex flex-1 min-h-0">
        {/* Sidebar — hidden during search */}
        {sidebarOpen && !isSearching && (
          <div className="w-64 border-r border-[var(--border)] bg-[var(--bg2)] shrink-0">
            <FilterPanel />
          </div>
        )}

        {/* Main grid area */}
        <div className="flex-1 min-w-0">
          {isLoading && (
            <div className="flex items-center justify-center h-full text-[var(--text-dim)]">
              {isSearching ? 'Searching...' : 'Loading images...'}
            </div>
          )}
          {isError && (
            <div className="flex items-center justify-center h-full text-[var(--reject)]">
              Error: {error?.message ?? 'Failed to load images'}
              <br />
              <span className="text-xs text-[var(--text-dim)]">
                {isSearching ? 'Is Ollama running?' : 'Is the API running on port 5001?'}
              </span>
            </div>
          )}
          {!isLoading && !isError && images.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full text-[var(--text-dim)] gap-3">
              {isSearching ? (
                <>
                  <Search size={40} className="opacity-30" />
                  <p>No results for "{searchQuery}"</p>
                  <p className="text-xs">Try different terms, or check that Ollama is running</p>
                </>
              ) : Object.values(filters).some(Boolean) ? (
                <>
                  <SlidersHorizontal size={40} className="opacity-30" />
                  <p>No images match current filters</p>
                  <button onClick={clearFilters} className="text-xs text-[var(--accent)] hover:underline">Clear all filters</button>
                </>
              ) : (
                <>
                  <Camera size={40} className="opacity-30" />
                  <p>No images yet</p>
                  <p className="text-xs">Run <code className="text-[var(--accent)]">dam ingest</code> to import photos</p>
                </>
              )}
            </div>
          )}
          {!isLoading && !isError && images.length > 0 && viewMode === 'grid' && (
            <ImageGrid
              images={images}
              thumbSize={thumbSize}
              hasNextPage={isSearching ? false : (feed.hasNextPage ?? false)}
              isFetchingNextPage={isSearching ? false : feed.isFetchingNextPage}
              fetchNextPage={feed.fetchNextPage}
            />
          )}
          {!isLoading && !isError && images.length > 0 && viewMode === 'list' && (
            <ImageList
              images={images}
              hasNextPage={isSearching ? false : (feed.hasNextPage ?? false)}
              isFetchingNextPage={isSearching ? false : feed.isFetchingNextPage}
              fetchNextPage={feed.fetchNextPage}
            />
          )}
        </div>
      </div>

      <StatusBar totalFiltered={totalFiltered} totalLoaded={images.length} />
    </div>

    {/* Lightbox overlay */}
    {lightboxIndex !== null && images[lightboxIndex] && (
      <Lightbox
        image={images[lightboxIndex]}
        images={images}
        currentIndex={lightboxIndex}
        onClose={closeLightbox}
        onNavigate={setLightboxIndex}
      />
    )}

    {/* Keyboard shortcuts help */}
    {helpOpen && <KeyboardHelp onClose={toggleHelp} />}

    {/* Global toasts */}
    <ToastContainer />
  </>
  )
}
