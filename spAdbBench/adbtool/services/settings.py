from __future__ import annotations

import re

from PySide6.QtCore import QObject, Signal

from ..infrastructure.process import AdbProcess
from ..infrastructure.validation import quote_remote, validate_number
from .settings_history import SettingsEntry, SettingsHistoryStore


TABLES = frozenset({"global", "secure", "system"})
ANIMATION_KEYS = (
    "window_animation_scale",
    "transition_animation_scale",
    "animator_duration_scale",
)
KEY_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
ICON_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


def validate_table(table: str) -> str:
    normalized = (table or "").strip()
    if normalized not in TABLES:
        raise ValueError(f"设置表不合法: {table!r}")
    return normalized


def validate_key(key: str) -> str:
    normalized = (key or "").strip()
    if not KEY_RE.fullmatch(normalized):
        raise ValueError(f"设置键不合法: {key!r}")
    return normalized


def validate_value(value) -> str:
    text = str(value)
    if not text:
        raise ValueError("设置值不能为空")
    if any(char in text for char in ("\x00", "\n", "\r")):
        raise ValueError("设置值不能包含换行或空字符")
    if len(text) > 4096:
        raise ValueError("设置值过长")
    return text


def format_number(value: float) -> str:
    return f"{value:g}"


class SettingsService(QObject):
    written = Signal(object)

    def __init__(
        self,
        adb,
        history: SettingsHistoryStore,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.adb = adb
        self.history = history

    def get(
        self,
        serial: str,
        table: str,
        key: str,
        *,
        timeout_ms: int = 30000,
    ) -> AdbProcess:
        table = validate_table(table)
        key = validate_key(key)
        return self.adb.shell(
            serial,
            f"settings get {table} {key}",
            timeout_ms=timeout_ms,
        )

    def put(
        self,
        serial: str,
        table: str,
        key: str,
        value,
        *,
        timeout_ms: int = 30000,
    ) -> AdbProcess:
        table = validate_table(table)
        key = validate_key(key)
        text = validate_value(value)
        command = f"settings put {table} {key} {quote_remote(text)}"
        process = self.adb.shell(serial, command, timeout_ms=timeout_ms)

        def _record(result) -> None:
            if not result.ok:
                return
            entry = self.history.record(
                serial,
                table,
                key,
                text,
                command,
            )
            self.written.emit(entry)

        process.finished.connect(_record)
        return process

    def set_font_scale(self, serial: str, value: float) -> AdbProcess:
        scale = validate_number(value, 0.5, 3.0, "字体倍率")
        return self.put(serial, "system", "font_scale", format_number(scale))

    def set_animation_scale(
        self,
        serial: str,
        key: str,
        value: float,
    ) -> AdbProcess:
        if key not in ANIMATION_KEYS:
            raise ValueError(f"动画键不合法: {key!r}")
        scale = validate_number(value, 0.0, 10.0, "动画倍率")
        return self.put(serial, "global", key, format_number(scale))

    def set_screen_timeout(self, serial: str, seconds: int) -> AdbProcess:
        timeout = validate_number(seconds, 0, 65535, "锁屏时间")
        return self.put(
            serial,
            "system",
            "screen_off_timeout",
            str(int(timeout) * 1000),
        )

    def set_immersive(self, serial: str, enabled: bool) -> AdbProcess:
        value = "immersive.full=*" if enabled else "null"
        return self.put(serial, "global", "policy_control", value)

    def set_icon_blacklist(
        self,
        serial: str,
        icons: list[str] | tuple[str, ...],
    ) -> AdbProcess:
        cleaned: list[str] = []
        for icon in icons:
            value = (icon or "").strip()
            if not value:
                continue
            if not ICON_RE.fullmatch(value):
                raise ValueError(f"状态栏图标名不合法: {icon!r}")
            if value not in cleaned:
                cleaned.append(value)
        return self.put(
            serial,
            "secure",
            "icon_blacklist",
            ",".join(cleaned) if cleaned else "null",
        )


def display_command(
    table: str,
    key: str,
    value: str,
    *,
    write: bool = True,
) -> str:
    table = validate_table(table)
    key = validate_key(key)
    if write:
        return f"settings put {table} {key} {quote_remote(validate_value(value))}"
    return f"settings get {table} {key}"


__all__ = [
    "ANIMATION_KEYS",
    "SettingsEntry",
    "SettingsService",
    "TABLES",
    "display_command",
    "format_number",
    "validate_key",
    "validate_table",
    "validate_value",
]
