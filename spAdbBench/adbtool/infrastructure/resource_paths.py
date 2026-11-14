from __future__ import annotations

import os
from pathlib import Path

from .paths import project_root, resource_root


def portable_path(value: str | Path | None, root: Path | str | None = None) -> str:
    """Return a project-relative path when possible.

    Absolute paths outside the project are kept only when they still exist.
    Missing absolute paths (for example an old install directory after a
    rename) are cleared so callers can fall back to the bundled resource.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    path = Path(text).expanduser()
    if not path.is_absolute():
        return path.as_posix()
    base = Path(root) if root is not None else project_root()
    try:
        path_abs = Path(os.path.abspath(path))
        base_abs = Path(os.path.abspath(base))
        return path_abs.relative_to(base_abs).as_posix()
    except (OSError, ValueError):
        return str(path) if path.exists() else ""


def resolve_resource(
    configured: str | Path | None,
    default_relative: str,
    root: Path | str | None = None,
) -> Path:
    base = Path(root) if root is not None else project_root()
    default = Path(default_relative)
    candidates: list[Path] = []
    text = str(configured or "").strip()
    explicit_absolute = False
    if text:
        path = Path(text).expanduser()
        if path.is_absolute():
            explicit_absolute = True
            candidates.append(path)
        else:
            candidates.extend([base / path, resource_root() / path])
    if not explicit_absolute:
        candidates.extend([base / default, resource_root() / default])

    seen: set[str] = set()
    for candidate in candidates:
        try:
            key = str(candidate.resolve()).lower()
        except OSError:
            key = str(candidate).lower()
        if key in seen:
            continue
        seen.add(key)
        if candidate.is_file():
            return candidate

    tried = "、".join(str(candidate) for candidate in candidates)
    raise FileNotFoundError(f"未找到 {default_relative}，已尝试：{tried}")
