export interface PywebviewApi {
  set_title?: (title: string) => void
  start_ingest?: (card_path?: string) => Promise<{ status: string }> | { status: string }
  open_path?: (path: string) => Promise<{ status: string }> | { status: string }
  pick_folder?: () => Promise<string | null> | string | null
}

declare global {
  interface Window {
    pywebview?: {
      api?: PywebviewApi
    }
  }
}

export {}
