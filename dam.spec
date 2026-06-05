# PyInstaller spec for DAM (one-directory bundle; .app on macOS).
# Run from project root: pyinstaller dam.spec (or: make build)
# DAM_ROOT is always ~/Documents/dam — the bundle can live anywhere.
# Requires: pip install pyinstaller; exiftool and (for tag/search) Ollama are not bundled.
# NOTE: torch/transformers (SigLIP) are heavy and awkward to freeze; for Linux the
# recommended deployment is `make install` (venv launcher), not this PyInstaller bundle.

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

import sqlite_vec as _sv

block_cipher = None
root = Path(".")
gunicorn_hidden = collect_submodules("gunicorn")

# sqlite_vec native extension must be bundled explicitly — name is OS-specific.
_sv_dir = Path(_sv.__file__).parent
_VEC0 = {"darwin": "vec0.dylib", "win32": "vec0.dll"}.get(sys.platform, "vec0.so")
_sv_bins = [(str(_sv_dir / _VEC0), "sqlite_vec")]

a = Analysis(
    ["dam_runner.py"],
    pathex=[str(root)],
    binaries=_sv_bins,
    datas=[
        (str(root / "dam.py"), "."),
        (str(root / "dam_config.py"), "."),
        (str(root / "dam_db.py"), "."),
        (str(root / "dam_schema.py"), "."),
        (str(root / "platform_utils.py"), "."),
        (str(root / "storage_utils.py"), "."),
        (str(root / "ingest_pipeline.py"), "."),
        (str(root / "card_ingest.py"), "."),
        (str(root / "dam_scanner.py"), "."),
        (str(root / "dam_tagger.py"), "."),
        (str(root / "dam_siglip.py"), "."),
        (str(root / "dam_api.py"), "."),
        (str(root / "static"), "static"),
    ],
    hiddenimports=["flask", "sqlite_vec", "dam_api", "dam_config", "dam_db",
                   "dam_schema", "platform_utils", "storage_utils", "ingest_pipeline",
                   "dam_siglip", "webview"] + gunicorn_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# One-directory EXE (required for .app bundles in PyInstaller 7+)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="dam",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_mode=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="dam",
)

# macOS gets a proper .app bundle; on Linux/Windows the COLLECT dir (dist/dam/)
# already contains the runnable executable, so BUNDLE is skipped.
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="DAM.app",
        icon="assets/icon.icns",
        bundle_identifier="com.janinieminen.dam",
        info_plist={
            "NSHighResolutionCapable": "True",
            "CFBundleDisplayName": "DAM",
            "CFBundleShortVersionString": "0.1.0",
        },
    )
