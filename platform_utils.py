"""Cross-platform helpers for mounts, app launching, notifications, and background processes."""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import string
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


def is_windows() -> bool:
    return os.name == "nt"


def is_macos() -> bool:
    return sys.platform == "darwin"


def is_linux() -> bool:
    return sys.platform.startswith("linux")


# Filesystems that should NOT be treated as a local archive disk.
_NETWORK_FS = {
    "nfs", "nfs4", "cifs", "smbfs", "smb3", "afpfs", "ncpfs",
    "fuse.sshfs", "fuse.gvfsd-fuse", "fuse.rclone",
}


def linux_media_roots() -> list[Path]:
    """Directories under which removable/external media auto-mount on Linux.

    /run/media/<user> is the modern udisks2 location (GNOME, KDE, most distros).
    /media/<user> and /media are older udisks layouts; /mnt covers manual mounts.
    Returned even if they do not yet exist — callers filter on existence.
    """
    user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
    roots: list[Path] = []
    if user:
        roots.append(Path("/run/media") / user)
        roots.append(Path("/media") / user)
    roots.append(Path("/media"))
    roots.append(Path("/mnt"))
    seen: set[Path] = set()
    ordered: list[Path] = []
    for root in roots:
        if root not in seen:
            seen.add(root)
            ordered.append(root)
    return ordered


def _proc_mounts() -> dict[str, tuple[str, list[str]]]:
    """Map mountpoint -> (fstype, options) parsed from /proc/mounts (Linux)."""
    info: dict[str, tuple[str, list[str]]] = {}
    try:
        with open("/proc/mounts", "r", encoding="utf-8") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) < 4:
                    continue
                # fields: device mountpoint fstype options dump pass
                mountpoint = parts[1].replace("\\040", " ").replace("\\011", "\t")
                info[mountpoint] = (parts[2], parts[3].split(","))
    except OSError:
        pass
    return info


def volume_label(path: Path) -> str:
    """Return a human-friendly volume label for logs and filtering."""
    if is_windows():
        drive = path.drive or str(path).replace("\\", "").replace("/", "")
        return drive.rstrip(":")
    return path.name


@dataclass(frozen=True)
class MountInfo:
    path: Path
    label: str
    fs_type: str | None
    local: bool
    read_only: bool


_MOUNT_RE = re.compile(r"^.+? on (.+?) \((.+)\)$")


def list_mount_info() -> list[MountInfo]:
    """Enumerate mount roots with basic filesystem metadata."""
    if is_windows():
        infos: list[MountInfo] = []
        for letter in string.ascii_uppercase:
            drive = Path(f"{letter}:\\")
            if drive.exists():
                infos.append(
                    MountInfo(
                        path=drive,
                        label=volume_label(drive),
                        fs_type=None,
                        local=True,
                        read_only=not os.access(drive, os.W_OK),
                    )
                )
        return infos

    if is_linux():
        proc = _proc_mounts()
        infos = []
        seen: set[Path] = set()
        for base in linux_media_roots():
            if not base.is_dir():
                continue
            try:
                entries = sorted(base.iterdir())
            except OSError:
                continue
            for entry in entries:
                if entry in seen or not entry.is_dir():
                    continue
                if not os.path.ismount(entry):
                    continue
                seen.add(entry)
                fs_type, opts = proc.get(str(entry), (None, []))
                infos.append(
                    MountInfo(
                        path=entry,
                        label=volume_label(entry),
                        fs_type=fs_type,
                        local=fs_type not in _NETWORK_FS if fs_type else True,
                        read_only=("ro" in opts) or not os.access(entry, os.W_OK),
                    )
                )
        return infos

    result = subprocess.run(["mount"], capture_output=True, text=True, check=False)
    infos: list[MountInfo] = []
    for line in result.stdout.splitlines():
        match = _MOUNT_RE.match(line.strip())
        if not match:
            continue
        mount_path = Path(match.group(1))
        if not str(mount_path).startswith("/Volumes/"):
            continue
        opts = [part.strip() for part in match.group(2).split(",")]
        infos.append(
            MountInfo(
                path=mount_path,
                label=volume_label(mount_path),
                fs_type=opts[0] if opts else None,
                local="local" in opts,
                read_only="read-only" in opts or "ro" in opts,
            )
        )
    return infos


def iter_mount_points() -> list[Path]:
    """Enumerate mount roots visible on this OS."""
    return [info.path for info in list_mount_info()]


def is_dir_writable(path: Path) -> bool:
    """Cheap writability check for a mounted root."""
    return os.access(path, os.W_OK)


def free_bytes(path: Path) -> int:
    """Return free bytes for a path, or 0 if unavailable."""
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return 0


def find_archive_mounts(ignore_labels: set[str] | list[str] | tuple[str, ...]) -> list[MountInfo]:
    """Return mounted non-card archive candidates, including read-only browse shares."""
    ignore = {s.lower() for s in ignore_labels}
    mounts: list[MountInfo] = []
    for mount in list_mount_info():
        if mount.label.lower() in ignore:
            continue
        if (mount.path / "DCIM").is_dir():
            continue
        mounts.append(mount)
    return mounts


def find_dcim_mounts(ignore_labels: set[str] | list[str] | tuple[str, ...]) -> list[Path]:
    """Return mounted volumes that contain a DCIM folder."""
    ignore = {s.lower() for s in ignore_labels}
    mounts: list[Path] = []
    for mount in iter_mount_points():
        if volume_label(mount).lower() in ignore:
            continue
        if (mount / "DCIM").is_dir():
            mounts.append(mount)
    return mounts


def notify_desktop(title: str, message: str) -> None:
    """Best-effort desktop notification (no-op if the platform tool is unavailable)."""
    with contextlib.suppress(Exception):
        if is_macos():
            subprocess.run(
                ["osascript", "-e", f'display notification "{message}" with title "{title}"'],
                timeout=5,
                check=False,
            )
        elif is_linux() and shutil.which("notify-send"):
            subprocess.run(
                ["notify-send", "--app-name=DAM", title, message],
                timeout=5,
                check=False,
            )


def _find_monitor_python() -> str:
    """Find a Python interpreter that can run the PySide6 GUI monitor.

    On macOS, uv's standalone CPython builds fail to load Qt's cocoa platform
    plugin, so a Homebrew/framework Python is preferred. A dedicated monitor venv
    (created once via ``python3 -m venv ~/.local/dam-monitor && pip install PySide6``)
    works on every platform and takes priority. Falls back to the current interpreter.
    """
    candidates = [
        str(Path.home() / ".local" / "dam-monitor" / "bin" / "python3"),  # POSIX venv
        str(Path.home() / ".local" / "dam-monitor" / "Scripts" / "python.exe"),  # Windows venv
        "/opt/homebrew/bin/python3",  # macOS (Apple Silicon Homebrew)
        "/usr/local/bin/python3",  # macOS (Intel Homebrew) / Linux
        sys.executable,
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return sys.executable


def launch_ingest_monitor(vol_name: str) -> None:
    """Launch the PySide6 ingest monitor as a detached background subprocess.

    dest_root is NOT passed here — the monitor reads it from ingest_status.json
    once card_ingest.py starts writing it. No-op if the script or PySide6 is absent.
    """
    if not (is_macos() or is_linux() or is_windows()):
        return
    monitor_script = Path(__file__).parent / "ingest_monitor.py"
    if not monitor_script.exists():
        return

    python = _find_monitor_python()
    with contextlib.suppress(Exception):
        subprocess.Popen(
            [python, str(monitor_script), "--vol", vol_name],
            start_new_session=True,
        )


# Known Linux image / RAW / media applications, keyed by their PATH executable name.
# The name doubles as the launch command for open_path_external(app_name=...).
_LINUX_MEDIA_APPS = [
    "darktable", "rawtherapee", "art", "gimp", "krita", "digikam",
    "gwenview", "nomacs", "geeqie", "gthumb", "shotwell", "eog",
    "feh", "inkscape", "photoflow", "luminance-hdr",
    "kdenlive", "shotcut", "resolve", "davinci-resolve", "vlc", "mpv",
]


def list_desktop_apps() -> list[str]:
    """Return launchable media-app names suitable for open_path_external(app_name=...).

    - macOS: application bundle display names under /Applications (opened via ``open -a``)
    - Linux: known media executables found on PATH (run directly with the file argument)
    - Windows: empty (no reliable generic enumeration)
    """
    if is_macos():
        apps_dir = Path("/Applications")
        if not apps_dir.is_dir():
            return []
        return sorted(p.stem for p in apps_dir.glob("*.app"))
    if is_linux():
        return [name for name in _LINUX_MEDIA_APPS if shutil.which(name)]
    return []


def open_path_external(path: str | Path, app_name: str | None = None) -> None:
    """Open a file/path in an external application."""
    target = str(path)

    if is_macos():
        if app_name:
            subprocess.run(["open", "-a", app_name, target], check=True)
        else:
            subprocess.run(["open", target], check=True)
        return

    if is_windows():
        if app_name:
            subprocess.run([app_name, target], check=True)
        else:
            os.startfile(target)  # type: ignore[attr-defined]
        return

    if app_name:
        subprocess.run([app_name, target], check=True)
    else:
        subprocess.run(["xdg-open", target], check=True)


def reveal_path_external(path: str | Path) -> None:
    """Reveal a file in the native file manager, falling back to its parent folder."""
    target = Path(path)

    if is_macos():
        try:
            subprocess.run(["open", "-R", str(target)], check=True)
        except (subprocess.CalledProcessError, OSError):
            open_path_external(target.parent)
        return

    if is_windows():
        try:
            subprocess.run(["explorer", f"/select,{target}"], check=True)
        except (subprocess.CalledProcessError, OSError):
            open_path_external(target.parent)
        return

    if is_linux():
        # The freedesktop FileManager1 D-Bus interface selects the file inside its
        # folder; Nautilus, Dolphin, Nemo, Caja and PCManFM all implement it.
        # Path.as_uri() percent-encodes spaces/quotes, so the GVariant string is safe.
        try:
            uri = target.resolve().as_uri()
        except ValueError:
            open_path_external(target.parent)
            return
        attempts = [
            ["gdbus", "call", "--session",
             "--dest", "org.freedesktop.FileManager1",
             "--object-path", "/org/freedesktop/FileManager1",
             "--method", "org.freedesktop.FileManager1.ShowItems",
             f"['{uri}']", ""],
            ["dbus-send", "--session", "--print-reply",
             "--dest=org.freedesktop.FileManager1",
             "/org/freedesktop/FileManager1",
             "org.freedesktop.FileManager1.ShowItems",
             f"array:string:{uri}", "string:"],
        ]
        for cmd in attempts:
            if not shutil.which(cmd[0]):
                continue
            try:
                subprocess.run(
                    cmd, check=True, timeout=5,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                return
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
                continue
        open_path_external(target.parent)
        return

    open_path_external(target.parent)


def spawn_background_process(cmd: list[str], log_file: Path, cwd: Path | str | None = None) -> subprocess.Popen:
    """Spawn detached background process and redirect stdout/stderr to log_file."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    fh = open(log_file, "ab")
    kwargs: dict[str, object] = {
        "cwd": str(cwd) if cwd else None,
        "stdin": subprocess.DEVNULL,
        "stdout": fh,
        "stderr": subprocess.STDOUT,
    }
    if is_windows():
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "DETACHED_PROCESS", 0)
        kwargs["creationflags"] = flags
    else:
        kwargs["start_new_session"] = True

    try:
        proc = subprocess.Popen(cmd, **kwargs)
    finally:
        fh.close()
    return proc
