from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..infrastructure.validation import quote_remote
from .settings import validate_key, validate_table
from .settings_history import SettingsEntry


SnapshotUnavailable = Callable[[str], bool]


def _missing(value: str | None) -> bool:
    return value is None or not str(value).strip()


def _missing_or_null(value: str | None) -> bool:
    if _missing(value):
        return True
    return str(value).strip().lower() in {"null", "none"}


def _display_missing(value: str | None) -> bool:
    return _missing(value) or "reset" in str(value).lower()


@dataclass(frozen=True)
class SnapshotField:
    key: str
    label: str
    group: str
    read_command: str
    write_command: str
    kind: str = "raw"
    unavailable_when: SnapshotUnavailable | None = None
    reset_command: str = ""
    quote_value: bool = True


KINDS = frozenset({"raw", "int", "float", "bool", "package_list", "json"})


SNAPSHOT_FIELDS: list[SnapshotField] = [
    SnapshotField(
        key="display.size",
        label="分辨率",
        group="显示",
        read_command="wm size",
        write_command="wm size {value}",
        kind="raw",
        unavailable_when=_display_missing,
        reset_command="wm size reset",
        quote_value=False,
    ),
    SnapshotField(
        key="display.density",
        label="DPI",
        group="显示",
        read_command="wm density",
        write_command="wm density {value}",
        kind="int",
        unavailable_when=_display_missing,
        reset_command="wm density reset",
        quote_value=False,
    ),
    SnapshotField(
        key="system.font_scale",
        label="字体倍率",
        group="显示与动画",
        read_command="settings get system font_scale",
        write_command="settings put system font_scale {value}",
        kind="float",
        unavailable_when=_missing_or_null,
    ),
    SnapshotField(
        key="global.window_animation_scale",
        label="窗口动画倍率",
        group="显示与动画",
        read_command="settings get global window_animation_scale",
        write_command="settings put global window_animation_scale {value}",
        kind="float",
        unavailable_when=_missing_or_null,
    ),
    SnapshotField(
        key="global.transition_animation_scale",
        label="过渡动画倍率",
        group="显示与动画",
        read_command="settings get global transition_animation_scale",
        write_command="settings put global transition_animation_scale {value}",
        kind="float",
        unavailable_when=_missing_or_null,
    ),
    SnapshotField(
        key="global.animator_duration_scale",
        label="属性动画倍率",
        group="显示与动画",
        read_command="settings get global animator_duration_scale",
        write_command="settings put global animator_duration_scale {value}",
        kind="float",
        unavailable_when=_missing_or_null,
    ),
    SnapshotField(
        key="system.screen_off_timeout",
        label="自动锁屏",
        group="显示与动画",
        read_command="settings get system screen_off_timeout",
        write_command="settings put system screen_off_timeout {value}",
        kind="int",
        unavailable_when=_missing_or_null,
    ),
    SnapshotField(
        key="global.policy_control",
        label="沉浸模式",
        group="显示与动画",
        read_command="settings get global policy_control",
        write_command="settings put global policy_control {value}",
        kind="raw",
        unavailable_when=_missing,
    ),
    SnapshotField(
        key="secure.icon_blacklist",
        label="状态栏图标隐藏",
        group="状态栏",
        read_command="settings get secure icon_blacklist",
        write_command="settings put secure icon_blacklist {value}",
        kind="raw",
        unavailable_when=_missing,
    ),
    SnapshotField(
        key="packages.disabled",
        label="已禁用应用",
        group="应用",
        read_command="pm list packages -d",
        write_command="pm disable-user --user 0 {value}",
        kind="package_list",
        unavailable_when=None,
        quote_value=False,
    ),
    SnapshotField(
        key="battery.simulation",
        label="电池模拟",
        group="电池",
        read_command="dumpsys battery",
        write_command="dumpsys battery reset",
        kind="json",
        unavailable_when=None,
        reset_command="dumpsys battery reset",
        quote_value=False,
    ),
]


def render_read(field: SnapshotField) -> str:
    if not field.read_command:
        raise ValueError(f"快照字段缺少读取命令: {field.key}")
    return field.read_command


def render_write(field: SnapshotField, value) -> str:
    if value is None:
        if field.reset_command:
            return field.reset_command
        raise ValueError(f"快照字段没有可用值，无法生成写入命令: {field.key}")
    text = str(value).strip()
    if not text:
        if field.reset_command:
            return field.reset_command
        raise ValueError(f"快照字段的写入值为空: {field.key}")
    encoded = quote_remote(text) if field.quote_value else text
    if "{value}" not in field.write_command:
        return field.write_command
    return field.write_command.replace("{value}", encoded)


def build_dynamic_settings_fields(entries: list[SettingsEntry]) -> list[SnapshotField]:
    order: list[str] = []
    latest: dict[str, SettingsEntry] = {}
    for entry in entries:
        try:
            table = validate_table(entry.table)
            key = validate_key(entry.key)
        except ValueError:
            continue
        field_key = f"settings.{table}.{key}"
        if field_key not in latest:
            order.append(field_key)
        latest[field_key] = entry

    fields: list[SnapshotField] = []
    for field_key in order:
        entry = latest[field_key]
        table = validate_table(entry.table)
        key = validate_key(entry.key)
        fields.append(
            SnapshotField(
                key=field_key,
                label=f"{table}/{key}",
                group="历史设置",
                read_command=f"settings get {table} {key}",
                write_command=f"settings put {table} {key} {{value}}",
                kind="raw",
                unavailable_when=_missing,
            )
        )
    return fields


__all__ = [
    "KINDS",
    "SNAPSHOT_FIELDS",
    "SnapshotField",
    "build_dynamic_settings_fields",
    "render_read",
    "render_write",
]
