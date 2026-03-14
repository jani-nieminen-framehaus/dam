# PyInstaller spec for DAM (one-file build).
# Run from project root: pyinstaller dam.spec
# Put the built executable (dist/dam) in your project root; it uses that dir as DAM_ROOT for DB, static, thumbs.
# Requires: pip install pyinstaller; exiftool and (for tag/search) Ollama are not bundled.

from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None
root = Path(".")
gunicorn_hidden = collect_submodules("gunicorn")

a = Analysis(
    ["dam_runner.py"],
    pathex=[str(root)],
    binaries=[],
    datas=[
        (str(root / "dam.py"), "."),
        (str(root / "card_ingest.py"), "."),
        (str(root / "dam_scanner.py"), "."),
        (str(root / "dam_tagger.py"), "."),
        (str(root / "dam_api.py"), "."),
    ],
    hiddenimports=["flask", "sqlite_vec", "dam_api", "webview"] + gunicorn_hidden,
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

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
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

app = BUNDLE(
    exe,
    name="DAM.app",
    icon=None,
    bundle_identifier="com.dam.app",
    info_plist={
        "NSHighResolutionCapable": "True"
    },
)
