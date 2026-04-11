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
    """Best-effort desktop notification."""
    if is_macos():
        subprocess.run(
            ["osascript", "-e", f'display notification "{message}" with title "{title}"'],
            timeout=5,
            check=False,
        )


def launch_ingest_monitor(vol_name: str) -> None:
    """Launch the PySide6 ingest monitor as a detached background subprocess.

    dest_root is NOT passed here — the monitor reads it from ingest_status.json
    once card_ingest.py starts writing it. No-op on Linux or if script is absent.
    """
    if sys.platform not in ("darwin", "win32"):
        return
    monitor_script = Path(__file__).parent / "ingest_monitor.py"
    if not monitor_script.exists():
        return
    with contextlib.suppress(Exception):
        subprocess.Popen(
            [sys.executable, str(monitor_script), "--vol", vol_name],
            start_new_session=True,
        )


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
