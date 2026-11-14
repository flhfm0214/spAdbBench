from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject

from ..infrastructure.parsers import parse_wm_density, parse_wm_size
from ..infrastructure.validation import validate_int
from .adb import AdbService


INFO_SCRIPT = "echo __SIZE__; wm size; echo __DENSITY__; wm density"
SCREENSHOT_SUFFIX = ".png"


@dataclass(frozen=True)
class KeyEvent:
    label: str
    code: int
    group: str


KEY_EVENTS: dict[str, KeyEvent] = {
    "home": KeyEvent("主页", 3, "导航"),
    "back": KeyEvent("返回", 4, "导航"),
    "recent": KeyEvent("最近任务", 187, "导航"),
    "menu": KeyEvent("菜单", 82, "导航"),
    "dpad_up": KeyEvent("上", 19, "方向"),
    "dpad_down": KeyEvent("下", 20, "方向"),
    "dpad_left": KeyEvent("左", 21, "方向"),
    "dpad_right": KeyEvent("右", 22, "方向"),
    "dpad_center": KeyEvent("确定", 23, "方向"),
    "power": KeyEvent("电源", 26, "电源与音量"),
    "wakeup": KeyEvent("唤醒", 224, "电源与音量"),
    "sleep": KeyEvent("休眠", 223, "电源与音量"),
    "volume_up": KeyEvent("音量 +", 24, "电源与音量"),
    "volume_down": KeyEvent("音量 -", 25, "电源与音量"),
    "volume_mute": KeyEvent("静音", 164, "电源与音量"),
    "enter": KeyEvent("回车", 66, "输入"),
    "delete": KeyEvent("删除", 67, "输入"),
    "camera": KeyEvent("相机", 27, "媒体"),
    "media_play_pause": KeyEvent("播放/暂停", 85, "媒体"),
    "media_next": KeyEvent("下一首", 87, "媒体"),
    "media_previous": KeyEvent("上一首", 88, "媒体"),
}

KEY_GROUPS = ("导航", "方向", "电源与音量", "输入", "媒体")


@dataclass(frozen=True)
class DisplayInfo:
    effective_size: str = ""
    physical_size: str = ""
    effective_density: int | None = None
    physical_density: int | None = None
    size_overridden: bool = False
    density_overridden: bool = False


def parse_display_info(text: str) -> DisplayInfo:
    size_text, _, density_text = (text or "").partition("__DENSITY__")
    size_text = size_text.replace("__SIZE__", "")
    effective_size, physical_size = parse_wm_size(size_text)
    density_override, physical_density = parse_wm_density(density_text)
    return DisplayInfo(
        effective_size=effective_size or "",
        physical_size=physical_size or "",
        effective_density=density_override
        if density_override is not None
        else physical_density,
        physical_density=physical_density,
        size_overridden="Override size:" in size_text,
        density_overridden="Override density:" in density_text,
    )


def screenshot_destination(
    serial: str,
    directory: Path | str,
    timestamp: str | None = None,
) -> Path:
    safe_serial = re.sub(r"[^A-Za-z0-9._-]+", "_", serial or "device").strip("._-")
    if not safe_serial:
        safe_serial = "device"
    stamp = timestamp or datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return Path(directory) / f"{safe_serial}-{stamp}{SCREENSHOT_SUFFIX}"


class DisplayService(QObject):
    def __init__(self, adb: AdbService, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.adb = adb

    def info_argv(self, serial: str) -> list[str]:
        return self.adb.shell_argv(serial, INFO_SCRIPT)

    def set_size_argv(self, serial: str, width: int, height: int) -> list[str]:
        width = validate_int(width, 200, 10000, "宽度")
        height = validate_int(height, 200, 10000, "高度")
        return self.adb.shell_argv(serial, f"wm size {width}x{height}")

    def reset_size_argv(self, serial: str) -> list[str]:
        return self.adb.shell_argv(serial, "wm size reset")

    def set_density_argv(self, serial: str, density: int) -> list[str]:
        density = validate_int(density, 72, 1000, "DPI")
        return self.adb.shell_argv(serial, f"wm density {density}")

    def reset_density_argv(self, serial: str) -> list[str]:
        return self.adb.shell_argv(serial, "wm density reset")

    def key_argv(self, serial: str, key: str) -> list[str]:
        try:
            event = KEY_EVENTS[key]
        except KeyError as exc:
            raise ValueError(f"未知按键: {key}") from exc
        return self.adb.shell_argv(serial, f"input keyevent {event.code}")

    def screenshot_argv(self, serial: str) -> list[str]:
        return self.adb.build(serial, "exec-out", "screencap", "-p")

    def info(self, serial: str):
        return self.adb.run_argv(self.info_argv(serial), timeout_ms=15000)

    def set_size(self, serial: str, width: int, height: int):
        return self.adb.run_argv(self.set_size_argv(serial, width, height), timeout_ms=15000)

    def reset_size(self, serial: str):
        return self.adb.run_argv(self.reset_size_argv(serial), timeout_ms=15000)

    def set_density(self, serial: str, density: int):
        return self.adb.run_argv(self.set_density_argv(serial, density), timeout_ms=15000)

    def reset_density(self, serial: str):
        return self.adb.run_argv(self.reset_density_argv(serial), timeout_ms=15000)

    def send_key(self, serial: str, key: str):
        return self.adb.run_argv(self.key_argv(serial, key), timeout_ms=10000)

    def screenshot(self, serial: str, destination: Path | str):
        path = Path(destination)
        if path.suffix.lower() != SCREENSHOT_SUFFIX:
            raise ValueError("截图文件名必须以 .png 结尾")
        path.parent.mkdir(parents=True, exist_ok=True)
        return self.adb.run_argv_to_file(
            self.screenshot_argv(serial),
            path,
            timeout_ms=30000,
        )
