from __future__ import annotations

import os
import shutil
from pathlib import Path

from .config import AppConfig
from .paths import PROJECT_ROOT


class AdbNotFoundError(FileNotFoundError):
    pass


def _adb_name() -> str:
    return "adb.exe" if os.name == "nt" else "adb"


def resolve_adb(
    config: AppConfig,
    project_root: Path | None = None,
    which=shutil.which,
) -> Path:
    root = Path(project_root) if project_root is not None else PROJECT_ROOT
    candidates: list[Path] = []

    if config.adb_path:
        configured = Path(config.adb_path).expanduser()
        if not configured.is_absolute():
            configured = root / configured
        candidates.append(configured)
        if configured.is_file():
            return configured

    bundled = root / "platform-tools" / _adb_name()
    candidates.append(bundled)
    if bundled.is_file():
        return bundled

    from_path = which("adb")
    if from_path:
        path_candidate = Path(from_path)
        candidates.append(path_candidate)
        if path_candidate.is_file():
            return path_candidate

    tried = ", ".join(str(path) for path in candidates) or "（没有候选路径）"
    raise AdbNotFoundError(f"未找到 adb，已尝试: {tried}")
