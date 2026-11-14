from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QProcess, QUrl
from PySide6.QtGui import QDesktopServices


def open_folder(
    path: str | Path,
    *,
    platform: str | None = None,
    start_detached: Callable[[str, list[str]], object] | None = None,
    open_url: Callable[[QUrl], bool] | None = None,
) -> bool:
    """Open a folder in the platform file manager.

    Windows Explorer is started directly instead of going through
    ShellExecute, which can fail with access denied on some project folders.
    """
    target = Path(path).expanduser()
    try:
        if not target.is_dir():
            return False
        target = target.resolve()
    except OSError:
        return False

    if (platform or sys.platform) == "win32":
        starter = start_detached or QProcess.startDetached
        try:
            result = starter("explorer.exe", [str(target)])
        except (OSError, RuntimeError):
            return False
        if isinstance(result, tuple):
            return bool(result[0])
        return bool(result)

    opener = open_url or QDesktopServices.openUrl
    try:
        return bool(opener(QUrl.fromLocalFile(str(target))))
    except (OSError, RuntimeError):
        return False
