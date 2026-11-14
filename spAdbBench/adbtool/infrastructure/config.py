from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .paths import (
    default_data_dir,
    default_save_dir,
    default_script_dir,
    default_screenshot_dir,
    default_snapshot_dir,
)
from .resource_paths import portable_path


logger = logging.getLogger(__name__)


def _as_bool(value, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
    return fallback


def _clamp_int(value, low: int, high: int, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, number))


@dataclass
class AppConfig:
    adb_path: str = ""
    scrcpy_server_path: str = ""
    default_serial: str = ""
    metrics_interval_ms: int = 1000
    device_poll_ms: int = 1000
    theme: str = "dark"
    scrcpy_max_fps: int = 30
    scrcpy_max_size: int = 1080
    scrcpy_bit_rate: int = 8_000_000
    preview_fps: int = 1
    auto_refresh_devices: bool = False
    auto_start_preview: bool = True
    preview_auto_close_enabled: bool = True
    preview_auto_close_seconds: int = 60
    detection_settings_version: int = 2
    theme_settings_version: int = 2
    save_dir: str = field(default_factory=lambda: str(default_save_dir()))
    snapshot_dir: str = field(default_factory=lambda: str(default_snapshot_dir()))
    script_dir: str = field(default_factory=lambda: str(default_script_dir()))
    screenshot_dir: str = field(default_factory=lambda: str(default_screenshot_dir()))

    @property
    def save_root(self) -> Path:
        text = (self.save_dir or "").strip()
        return Path(text) if text else default_save_dir()

    @classmethod
    def from_dict(cls, raw: dict) -> "AppConfig":
        known = {f.name for f in fields(cls)}
        data = asdict(cls())
        data.update({key: value for key, value in raw.items() if key in known})
        config = cls(**data)
        if config.theme not in {"system", "light", "dark"}:
            config.theme = "dark"
        try:
            interval = int(config.metrics_interval_ms)
            config.metrics_interval_ms = 0 if interval <= 0 else max(100, min(60000, interval))
        except (TypeError, ValueError):
            config.metrics_interval_ms = 1000
        config.device_poll_ms = _clamp_int(config.device_poll_ms, 200, 60000, 1000)
        config.scrcpy_max_fps = _clamp_int(config.scrcpy_max_fps, 1, 60, 30)
        config.scrcpy_max_size = _clamp_int(config.scrcpy_max_size, 320, 4096, 1080)
        config.scrcpy_bit_rate = _clamp_int(
            config.scrcpy_bit_rate, 500_000, 50_000_000, 8_000_000
        )
        config.preview_fps = _clamp_int(config.preview_fps, 1, 60, 1)
        config.auto_refresh_devices = _as_bool(config.auto_refresh_devices, False)
        config.auto_start_preview = _as_bool(config.auto_start_preview, True)
        config.preview_auto_close_enabled = _as_bool(
            config.preview_auto_close_enabled,
            True,
        )
        config.preview_auto_close_seconds = _clamp_int(
            config.preview_auto_close_seconds,
            10,
            3600,
            60,
        )
        # Device detection used to be enabled by default.  Migrate old configs
        # once so existing installations also start with detection off; a later
        # save records the user's explicit choice.
        try:
            detection_version = int(raw.get("detection_settings_version", 1))
        except (TypeError, ValueError):
            detection_version = 1
        if detection_version < 2:
            config.auto_refresh_devices = False
        config.detection_settings_version = 2
        try:
            theme_version = int(raw.get("theme_settings_version", 1))
        except (TypeError, ValueError):
            theme_version = 1
        if theme_version < 2 and config.theme == "system":
            config.theme = "dark"
        config.theme_settings_version = 2

        save_text = str(config.save_dir or "").strip()
        config.save_dir = str(Path(save_text).expanduser()) if save_text else str(default_save_dir())
        if not str(config.snapshot_dir or "").strip():
            config.snapshot_dir = str(Path(config.save_dir) / "snapshots")
        if not str(config.screenshot_dir or "").strip():
            config.screenshot_dir = str(Path(config.save_dir) / "screenshots")
        return config


class ConfigStore:
    def __init__(self, project_root: Path) -> None:
        self.root = Path(project_root)
        self.path = self.root / "config" / "settings.json"

    def load(self) -> AppConfig:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return AppConfig()
        except (OSError, ValueError) as exc:
            logger.warning("读取配置失败，使用默认值: %s", exc)
            return AppConfig()
        if not isinstance(raw, dict):
            logger.warning("配置文件顶层不是对象，使用默认值")
            return AppConfig()
        config = AppConfig.from_dict(raw)
        config.adb_path = portable_path(config.adb_path, self.root)
        config.scrcpy_server_path = portable_path(config.scrcpy_server_path, self.root)
        return config

    def save(self, config: AppConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(".tmp")
        data = asdict(config)
        data["adb_path"] = portable_path(config.adb_path, self.root)
        data["scrcpy_server_path"] = portable_path(config.scrcpy_server_path, self.root)
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        temp_path.write_text(payload + "\n", encoding="utf-8")
        os.replace(temp_path, self.path)


__all__ = ["AppConfig", "ConfigStore", "default_data_dir"]
