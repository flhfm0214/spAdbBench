from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FROZEN = bool(getattr(sys, "frozen", False))
# PyInstaller extracts bundled data below ``sys._MEIPASS``; mutable files such
# as config/settings.json and data/ must live beside the executable.
BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))
APP_ROOT = Path(sys.executable).resolve().parent if FROZEN else PROJECT_ROOT


def project_root() -> Path:
    return APP_ROOT


def resource_root() -> Path:
    return BUNDLE_ROOT


def frozen() -> bool:
    return FROZEN


def vendor_scrcpy_server() -> Path:
    return resource_root() / "vendor" / "scrcpy" / "scrcpy-server"


def vendor_scrcpy_exe() -> Path:
    return resource_root() / "vendor" / "scrcpy" / "native" / "scrcpy.exe"


def default_config_path() -> Path:
    return APP_ROOT / "config" / "settings.json"


def default_data_dir() -> Path:
    return APP_ROOT / "data"


def default_execution_log() -> Path:
    return default_data_dir() / "execution-log.jsonl"


def default_save_dir() -> Path:
    return Path.home() / "Documents" / "adb-utils"


def default_snapshot_dir() -> Path:
    return default_save_dir() / "snapshots"


def default_script_dir() -> Path:
    return APP_ROOT / "scripts"


def default_screenshot_dir() -> Path:
    return default_save_dir() / "screenshots"
