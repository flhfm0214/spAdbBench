from __future__ import annotations

import posixpath
from dataclasses import dataclass

from ..infrastructure.process import AdbProcess
from ..infrastructure.validation import quote_remote, validate_remote_path
from .adb import AdbService


@dataclass(frozen=True)
class RemoteEntry:
    name: str
    path: str
    permissions: str
    owner: str
    group: str
    size: int
    modified: str
    is_dir: bool
    is_link: bool = False
    link_target: str = ""

    @property
    def mode(self) -> str:
        """Symbolic permissions without the leading file-type character."""
        return self.permissions[1:] or self.permissions


def normalize_remote_path(path: str) -> str:
    value = (path or "/").strip()
    if not value.startswith("/"):
        value = "/" + value
    normalized = posixpath.normpath(value)
    if normalized.startswith("//"):
        normalized = "/" + normalized.lstrip("/")
    return normalized or "/"


def _entry_from_line(directory: str, line: str) -> RemoteEntry | None:
    if not line or line.startswith("total "):
        return None
    parts = line.split(None, 7)
    if len(parts) < 8:
        return None
    permissions, _links, owner, group, raw_size, date, time, name = parts
    if len(permissions) < 10 or permissions[0] not in "-dlcbps":
        return None
    if name in {".", ".."}:
        return None
    is_link = permissions.startswith("l")
    link_target = ""
    if is_link and " -> " in name:
        name, link_target = name.split(" -> ", 1)
    if not name:
        return None
    try:
        size = int(raw_size)
    except ValueError:
        size = 0
    return RemoteEntry(
        name=name,
        path=normalize_remote_path(posixpath.join(directory, name)),
        permissions=permissions,
        owner=owner,
        group=group,
        size=size,
        modified=f"{date} {time}",
        is_dir=permissions.startswith("d"),
        is_link=is_link,
        link_target=link_target,
    )


def parse_ls_output(directory: str, text: str) -> list[RemoteEntry]:
    directory = normalize_remote_path(directory)
    entries: list[RemoteEntry] = []
    for raw_line in (text or "").splitlines():
        entry = _entry_from_line(directory, raw_line.strip())
        if entry is not None:
            entries.append(entry)
    entries.sort(key=lambda entry: (not entry.is_dir, entry.name.casefold()))
    return entries


def format_size(size: int, is_dir: bool) -> str:
    if is_dir:
        return "—"
    if size < 1024:
        return f"{size} B"
    value = float(size)
    for unit in ("KB", "MB", "GB", "TB"):
        value /= 1024.0
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
    return f"{size} B"


class RemoteFileService:
    """Small `ls` based reader for the device filesystem."""

    def __init__(self, adb: AdbService) -> None:
        self.adb = adb

    def list(self, serial: str, path: str) -> AdbProcess:
        remote_path = validate_remote_path(normalize_remote_path(path))
        # A trailing slash and -L make mounted symlinks such as /sdcard list
        # their contents instead of showing the symlink itself.
        command_path = remote_path if remote_path == "/" else remote_path + "/"
        command = f"ls -laL {quote_remote(command_path)}"
        return self.adb.shell(serial, command, timeout_ms=15000, record=False)
