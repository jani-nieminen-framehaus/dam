# Packaging and running DAM

The project runs as an **installable CLI + web app** and can be built into a
**standalone bundle** — a `.app` on macOS, a one-directory bundle on Linux.

DAM is cross-platform (Linux + macOS). Removable archive/card volumes are detected
under each OS's mount root automatically:

| OS    | Volumes mount under          |
|-------|------------------------------|
| Linux | `/run/media/<user>/<label>` (udisks2), `/media`, `/mnt` |
| macOS | `/Volumes/<label>`           |

---

## Quick start

```bash
make run          # Launch desktop app (development, from source)
make serve        # Web server only (localhost:5001)
make test         # Run all tests
make build        # Full build: frontend + bundle
make clean        # Remove build artifacts
```

`make` auto-detects the interpreter: it prefers `uv` (project venv), then `.venv/`,
then system `python3`.

---

## 1. Installable app (recommended for development)

With **uv** (recommended):

```bash
uv sync                 # create .venv and install all dependencies
```

Or with a plain venv:

```bash
python3 -m venv .venv
source .venv/bin/activate          # Linux/macOS
pip install -e ".[serve]"
```

> **torch note (Linux):** the default PyPI `torch` wheel ships CUDA. For a CPU-only
> box install it from the CPU index *first*, then sync the rest:
> `pip install torch --index-url https://download.pytorch.org/whl/cpu`
> (use the ROCm index for AMD GPUs). See `requirements.txt`.

Then run any command via `dam` (or `uv run python dam.py …`):

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
- **exiftool** — `sudo pacman -S perl-image-exiftool` (Arch) / `sudo apt install libimage-exiftool-perl` (Debian) / `brew install exiftool` (macOS)
- **Ollama** (optional) — for `dam tag` and `dam search`
- **pywebview GUI backend** (only for `dam serve --window` as a native window):
  - Linux: `sudo pacman -S python-gobject webkit2gtk-4.1` (Arch) / `sudo apt install python3-gi gir1.2-webkit2-4.1` (Debian). Without a backend, `--window` falls back to opening the default web browser.
  - macOS: built-in WKWebView, no extra packages.

---

## 2. Linux desktop integration

```bash
make install          # install `dam` launcher + .desktop entry into ~/.local
make watcher-install  # enable the SD/CFexpress card-watcher as a systemd --user service
```

- `make install` writes `~/.local/bin/dam` (a launcher that runs this checkout) and
  `~/.local/share/applications/dam.desktop`. Ensure `~/.local/bin` is on your `PATH`.
- `make watcher-install` is the Linux replacement for the macOS LaunchAgent: it enables
  `dam-card-watcher.service`, which polls mounted volumes for a `DCIM/` folder and fires
  the ingest pipeline on card insert. Logs: `journalctl --user -u dam-card-watcher -f`.
- Remove with `make uninstall` / `make watcher-uninstall`.

---

## 3. Standalone app (PyInstaller)

```bash
make build
```

This builds the frontend (`static/`) and then runs PyInstaller, producing:

- **macOS:** `dist/DAM.app` — application bundle. Drag to `/Applications` or keep anywhere.
- **Linux:** `dist/dam/` — one-directory bundle containing the `dam` executable.

> The bundle embeds the OS-specific `sqlite_vec` native library automatically
> (`vec0.dylib` on macOS, `vec0.so` on Linux). On Linux, freezing torch/transformers
> is heavy and fragile — the `make install` venv launcher above is the recommended
> deployment; the PyInstaller bundle is best suited to the lighter CLI/serve paths.

### Data location

DAM_ROOT is always `~/Documents/dam` regardless of where the bundle lives. The database
(`dam.db`), thumbnails (`thumbs/`), and web assets (`static/`) all live there.

To override DAM_ROOT, edit `~/.dam/config.json`:

```json
{
  "dam_root": "/path/to/your/dam"
}
```

### Rebuilding

After code changes, rebuild with `make build`. The `make frontend` target rebuilds just
the web UI; `make backend` rebuilds just the PyInstaller bundle.

---

## 4. Summary

| Goal                         | Command                          |
|------------------------------|----------------------------------|
| Dev: desktop app             | `make run`                       |
| Dev: web server              | `make serve`                     |
| Full build                   | `make build`                     |
| Linux launcher + desktop entry | `make install`                 |
| Linux card-watcher service   | `make watcher-install`           |
| Run tests                    | `make test`                      |
| External tools               | exiftool (required), Ollama (optional) |
