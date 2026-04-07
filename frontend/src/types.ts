/* DAM API types — matches Flask JSON responses exactly */

export interface DamImage {
  id: number
  file_path: string
  file_name: string
  file_type: string | null
  file_size: number | null
  volume: string | null
  relative_path: string | null
  date_folder: string | null

  // EXIF: camera
  camera_make: string | null
  camera_model: string | null
  camera_short: string | null
  mount: string | null

  // EXIF: lens
  lens_model: string | null

  // EXIF: exposure
  date_taken: string | null
  aperture: number | null
  shutter_speed: string | null
  iso: number | null
  focal_length: number | null
  focal_length_35eq: number | null

  // Workflow
  rating: number
  pick: 'pick' | 'reject' | 'unmarked'
  edit_status: string
  color_label: string
  is_selkie: boolean
  notes: string | null

  // AI
  ai_description: string | null
  ai_tagged_at: string | null

  // Triptych
  triptych_leg: string | null
  narrative_arc: string | null
  location_type: string | null

  // Many-to-many (JSON arrays from API)
  projects: string[]
  subjects: string[]
  keywords: string[]

  // Sidecars
  has_jpeg: boolean
  width: number | null
  height: number | null
}

export interface Cursor {
  date: string
  id: number
}

export interface ImagesResponse {
  images: DamImage[]
  next_cursor: Cursor | null
  total_filtered: number
}

export interface FiltersResponse {
  cameras: string[]
  volumes: string[]
  triptych_legs: string[]
  pick_values: string[]
  edit_status_values: string[]
  color_values: string[]
  triptych_values: string[]
  narrative_values: string[]
  location_types: string[]
  projects: string[]
  subjects: string[]
  date_min: string | null
  date_max: string | null
}

export interface StatsResponse {
  total: number
  thumbnails_cached: number
  by_camera: { camera: string; count: number }[]
  by_volume: { volume: string; count: number }[]
  by_edit_status: { status: string; count: number }[]
  by_pick: { pick: string; count: number }[]
}

export interface FilterState {
  camera?: string
  volume?: string
  pick?: string
  edit_status?: string
  color_label?: string
  rating_min?: number
  rating_max?: number
  project?: string
  subject?: string
  date_from?: string
  date_to?: string
}
