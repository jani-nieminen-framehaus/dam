# Packaging and running DAM

The project can be used as an **installable CLI + web app** and built into a **standalone macOS application**.

---

## Quick start

```bash
make run          # Launch desktop app (development, from source)
make serve        # Web server only (localhost:5001)
make test         # Run all tests
make build        # Full build: frontend + DAM.app
make clean        # Remove build artifacts
```

---

## 1. Installable app (recommended for development)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[serve]"
```

Then run any command via `dam`:

```bash
dam ingest              # Detect card, copy, scan, thumbnail, AI tag
dam scan                # Incremental scan of default volumes
dam thumbs              # Generate missing thumbnails
dam stats               # Show DB statistics
dam tag --limit 100     # AI tag images
dam search "isolation"  # Semantic search
dam serve               # Web API + SPA (gunicorn or Flask)
dam serve --window      # Desktop app (pywebview window)
dam export --dest ~/Out # Export picks to folder
dam config              # Show config
```

**External requirements** (not installed by pip):
- **exiftool** — `brew install exiftool`
- **Ollama** (optional) — for `dam tag` and `dam search`

---

## 2. Standalone app (PyInstaller)

```bash
make build
```

This builds the frontend (`static/`) and then runs PyInstaller, producing:

- **`dist/DAM.app`** — macOS application bundle. Drag to `/Applications` or keep anywhere.
- **`dist/dam`** — Standalone CLI executable.

### Data location

DAM_ROOT is always `~/Documents/dam` regardless of where the `.app` lives. The database (`dam.db`), thumbnails (`thumbs/`), and web assets (`static/`) all live there. This means you can freely move `DAM.app` to `/Applications` and it will still work.

To override DAM_ROOT, edit `~/.dam/config.json`:

```json
{
  "dam_root": "/path/to/your/dam"
}
```

### Rebuilding

After code changes, rebuild with `make build`. The `make frontend` target rebuilds just the web UI; `make backend` rebuilds just the PyInstaller bundle.

---

## 3. Summary

| Goal                         | Command                          |
|-----------------------------|----------------------------------|
| Dev: desktop app             | `make run`                       |
| Dev: web server              | `make serve`                     |
| Full build                   | `make build`                     |
| Run tests                    | `make test`                      |
| External tools               | exiftool (required), Ollama (optional) |
