import { useMemo } from 'react'
import { useImages } from './api/images'
import { useUIStore } from './stores/useUIStore'
import { Toolbar } from './components/layout/Toolbar'
import { StatusBar } from './components/layout/StatusBar'
import { FilterPanel } from './components/filters/FilterPanel'
import { ImageGrid } from './components/grid/ImageGrid'

export default function App() {
  const { filters, sidebarOpen, thumbSize } = useUIStore()
  const {
    data,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
    isLoading,
    isError,
    error,
  } = useImages(filters)

  const images = useMemo(
    () => data?.pages.flatMap((p) => p.images) ?? [],
    [data]
  )
  const totalFiltered = data?.pages[0]?.total_filtered ?? 0

  return (
    <div className="h-full flex flex-col">
      <Toolbar totalFiltered={totalFiltered} />

      <div className="flex flex-1 min-h-0">
        {/* Sidebar */}
        {sidebarOpen && (
          <div className="w-64 border-r border-[var(--border)] bg-[var(--bg2)] shrink-0">
            <FilterPanel />
          </div>
        )}

        {/* Main grid area */}
        <div className="flex-1 min-w-0">
          {isLoading && (
            <div className="flex items-center justify-center h-full text-[var(--text-dim)]">
              Loading images...
            </div>
          )}
          {isError && (
            <div className="flex items-center justify-center h-full text-[var(--reject)]">
              Error: {error?.message ?? 'Failed to load images'}
              <br />
              <span className="text-xs text-[var(--text-dim)]">Is the API running on port 5001?</span>
            </div>
          )}
          {!isLoading && !isError && (
            <ImageGrid
              images={images}
              thumbSize={thumbSize}
              hasNextPage={hasNextPage ?? false}
              isFetchingNextPage={isFetchingNextPage}
              fetchNextPage={fetchNextPage}
            />
          )}
        </div>
      </div>

      <StatusBar totalFiltered={totalFiltered} totalLoaded={images.length} />
    </div>
  )
}
