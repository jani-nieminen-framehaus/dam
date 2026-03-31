"""Storage identity and root-resolution helpers for archive volumes."""

from __future__ import annotations

import re
from pathlib import Path

from platform_utils import MountInfo, find_archive_mounts, free_bytes, is_dir_writable, volume_label


_TRAILING_NUMBER_RE = re.compile(r"(\d+)$")


def canonical_volume_label(label: str | None, aliases: dict[str, str] | None = None) -> str | None:
    """Map physical mount labels to stable logical archive labels."""
    if not label:
        return None

    alias_map = {k.lower(): v for k, v in (aliases or {}).items()}
    if label.lower() in alias_map:
        return alias_map[label.lower()]

    match = _TRAILING_NUMBER_RE.search(label.strip())
    if match:
        return f"Archive {int(match.group(1))}"

    return label


def logical_volume_for_root(root: str | Path, aliases: dict[str, str] | None = None) -> str | None:
    return canonical_volume_label(volume_label(Path(root)), aliases)


def relative_path_from_root(file_path: str | Path, root: str | Path) -> str | None:
    """Return a stable relative path within an archive root."""
    try:
        return str(Path(file_path).resolve().relative_to(Path(root).resolve()))
    except ValueError:
        return None


def _parse_windows_drive(raw: str, aliases: dict[str, str] | None) -> tuple[str | None, str | None] | None:
    """Parse a Windows drive letter path (e.g. D:\\Photos\\...). Returns None if not a drive path."""
    if len(raw) < 2 or raw[1] != ":" or not raw[0].isalpha():
        return None
    has_sep = len(raw) >= 3 and raw[2] in ("\\", "/")
    relative = raw[3:] if has_sep else raw[2:]
    return canonical_volume_label(raw[0].upper(), aliases), relative.lstrip("\\/") or None


def derive_legacy_identity(file_path: str | Path, aliases: dict[str, str] | None = None) -> tuple[str | None, str | None]:
    """Infer logical volume + relative path from legacy absolute file_path."""
    raw = str(file_path)
    path = Path(raw)

    win_result = _parse_windows_drive(raw, aliases)
    if win_result is not None:
        return win_result

    if path.drive:
        root = Path(f"{path.drive}\\")
        return logical_volume_for_root(root, aliases), relative_path_from_root(path, root)

    parts = path.parts
    if len(parts) >= 3 and parts[0] == "/" and parts[1] == "Volumes":
        root = Path(parts[0]) / parts[1] / parts[2]
        return logical_volume_for_root(root, aliases), relative_path_from_root(path, root)

    return None, None


def _mount_rank(info: MountInfo) -> tuple[int, int, int]:
    writable = int(is_dir_writable(info.path))
    local = int(info.local)
    return (local, writable, free_bytes(info.path))


def resolve_scan_roots(
    configured_roots: list[Path] | tuple[Path, ...] | None,
    ignore_labels: set[str] | list[str] | tuple[str, ...],
    aliases: dict[str, str] | None = None,
) -> list[Path]:
    """Resolve configured archive roots to the best currently mounted roots."""
    mounts = find_archive_mounts(ignore_labels)
    by_alias: dict[str | None, list[MountInfo]] = {}
    for mount in mounts:
        alias = canonical_volume_label(mount.label, aliases)
        by_alias.setdefault(alias, []).append(mount)

    def best_for(alias: str | None) -> Path | None:
        candidates = by_alias.get(alias, [])
        if not candidates:
            return None
        return max(candidates, key=_mount_rank).path

    resolved: list[Path] = []
    seen: set[Path] = set()

    if configured_roots:
        for root in configured_roots:
            alias = logical_volume_for_root(root, aliases)
            chosen = best_for(alias) or (root if root.exists() else None)
            if chosen and chosen not in seen:
                resolved.append(chosen)
                seen.add(chosen)
        return resolved

    local_writable = [m.path for m in sorted(mounts, key=_mount_rank, reverse=True) if m.local and not m.read_only]
    if local_writable:
        return local_writable
    return [m.path for m in sorted(mounts, key=_mount_rank, reverse=True)]


def choose_ingest_destination(
    preferred_root: str | Path | None,
    ignore_labels: set[str] | list[str] | tuple[str, ...],
    aliases: dict[str, str] | None = None,
) -> Path | None:
    """Choose a writable local archive root, preferring the logical match for preferred_root."""
    mounts = find_archive_mounts(ignore_labels)
    candidates = [m for m in mounts if m.local and is_dir_writable(m.path)]
    if not candidates:
        return None

    if preferred_root:
        preferred_alias = logical_volume_for_root(preferred_root, aliases)
        matching = [m for m in candidates if canonical_volume_label(m.label, aliases) == preferred_alias]
        if matching:
            return max(matching, key=_mount_rank).path

    return max(candidates, key=_mount_rank).path


def resolve_archive_file(
    file_path: str | Path,
    volume: str | None,
    relative_path: str | None,
    configured_roots: list[Path] | tuple[Path, ...] | None,
    ignore_labels: set[str] | list[str] | tuple[str, ...],
    aliases: dict[str, str] | None = None,
) -> Path | None:
    """Resolve a DB file reference against current mounted roots."""
    path = Path(file_path)
    if path.exists():
        return path

    logical_volume = volume
    rel_path = relative_path
    if logical_volume is None or rel_path is None:
        logical_volume, rel_path = derive_legacy_identity(path, aliases)
    if logical_volume is None or rel_path is None:
        return None

    for root in resolve_scan_roots(configured_roots, ignore_labels, aliases):
        if logical_volume_for_root(root, aliases) != logical_volume:
            continue
        candidate = root / rel_path
        if candidate.exists():
            return candidate
    return None
