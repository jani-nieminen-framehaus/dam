# Packaging and running DAM as an executable

The project can be used as an **installable CLI + web app** and optionally built into a **standalone executable**.

---

## 1. Installable app (recommended)

From the project root (`~/Documents/dam` or wherever you cloned it):

```bash
# Create a venv and install (use Python that has sqlite_vec — e.g. Homebrew Python on macOS)
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[serve]"
```

Then run any command via the single `dam` executable:

```bash
dam ingest
dam scan
dam thumbs
dam stats
dam tag --limit 100
dam search "isolation"
dam serve              # Web API + SPA (gunicorn if installed, else Flask)
dam serve --port 5001
```

**External requirements** (not installed by pip):

- **exiftool** — for ingest and scanner (install via Homebrew: `brew install exiftool`).
- **Ollama** (optional) — for `dam tag` and `dam search`; run Ollama locally with models `llava:34b`, `llama3.1:70b`, `nomic-embed-text`.

---

## 2. Standalone executable (PyInstaller)

You can build a single binary that bundles Python, Flask, and sqlite_vec. The result is a **CLI + server in one**; the web app is still a web app — you run `dam serve` and open the browser.

### One-folder build (simplest, recommended)

```bash
pip install pyinstaller
pyinstaller dam.spec
```

The executable and Mac application bundle will be located in `dist/`.

- `dist/DAM.app`: The native macOS double-clickable application bundle. It contains everything needed to run the desktop window interface.
- `dist/dam`: The standalone command-line executable bundle.

If using the `.app` bundle, simply place `DAM.app` into the `dam` folder containing your `static/`, `thumbs/`, and `dam.db` directories, and double-click to launch it seamlessly.

For command line execution:

```bash
./dist/dam/dam ingest
./dist/dam/dam serve
```

### One-file build

Possible but slower to start (extraction to a temp dir each run). You can duplicate the spec and set `EXE(..., onefile=True)`; data files (e.g. `static/`) must be handled via `--add-data` and `sys._MEIPASS` at runtime if you want them inside the bundle.

### Notes for PyInstaller

- **sqlite_vec**: Ensure the environment used to run PyInstaller has `sqlite-vec` installed; it will be bundled.
- **exiftool / Ollama**: Not bundled; the user must install them separately.
- **DAM_ROOT**: When running the frozen app, `DAM_ROOT` is set to the directory containing the executable, so keep the binary in the same folder as `static/`, `dam.db`, and (if desired) `thumbs/`.

---

## 3. Summary

| Goal                         | Approach                    |
|-----------------------------|-----------------------------|
| Single command, no “compile” | `pip install -e ".[serve]"` → `dam` |
| Web app + CLI in one place  | `dam serve` (same `dam` binary)     |
| Standalone binary           | PyInstaller with `dam.spec`         |
| External tools              | exiftool (required), Ollama (optional) |
