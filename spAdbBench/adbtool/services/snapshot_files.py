from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


SCHEMA_VERSION = 1


class SnapshotFormatError(ValueError):
    pass


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass(frozen=True)
class SnapshotItem:
    key: str
    label: str
    group: str
    value: str | None
    read_command: str
    write_command: str
    kind: str
    captured_ok: bool = True
    error: str = ""
    reset_command: str = ""
    quote_value: bool = True

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "group": self.group,
            "value": self.value,
            "read_command": self.read_command,
            "write_command": self.write_command,
            "kind": self.kind,
            "captured_ok": self.captured_ok,
            "error": self.error,
            "reset_command": self.reset_command,
            "quote_value": self.quote_value,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "SnapshotItem":
        if not isinstance(raw, dict):
            raise SnapshotFormatError("快照项必须是对象")
        for name in ("key", "read_command", "write_command"):
            if not raw.get(name):
                raise SnapshotFormatError(f"快照项缺少字段: {name}")
        value = raw.get("value")
        if value is not None and not isinstance(value, str):
            raise SnapshotFormatError("快照项 value 必须是字符串或 null")
        return cls(
            key=str(raw["key"]),
            label=str(raw.get("label") or raw["key"]),
            group=str(raw.get("group") or ""),
            value=value,
            read_command=str(raw["read_command"]),
            write_command=str(raw["write_command"]),
            kind=str(raw.get("kind") or "raw"),
            captured_ok=bool(raw.get("captured_ok", True)),
            error=str(raw.get("error") or ""),
            reset_command=str(raw.get("reset_command") or ""),
            quote_value=bool(raw.get("quote_value", True)),
        )


@dataclass(frozen=True)
class DeviceSnapshot:
    serial: str
    model: str
    captured_at: str
    items: dict[str, SnapshotItem] = field(default_factory=dict)
    disabled_packages: list[str] = field(default_factory=list)
    battery: dict = field(default_factory=dict)
    modified_settings: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "serial": self.serial,
            "model": self.model,
            "captured_at": self.captured_at,
            "items": {key: item.to_dict() for key, item in self.items.items()},
            "disabled_packages": list(self.disabled_packages),
            "battery": dict(self.battery),
            "modified_settings": dict(self.modified_settings),
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "DeviceSnapshot":
        if not isinstance(raw, dict):
            raise SnapshotFormatError("设备快照必须是对象")
        serial = str(raw.get("serial") or "")
        if not serial:
            raise SnapshotFormatError("设备快照缺少序列号")
        raw_items = raw.get("items")
        if not isinstance(raw_items, dict):
            raise SnapshotFormatError("设备快照 items 必须是对象")
        items = {
            str(key): SnapshotItem.from_dict(value)
            for key, value in raw_items.items()
        }
        return cls(
            serial=serial,
            model=str(raw.get("model") or ""),
            captured_at=str(raw.get("captured_at") or ""),
            items=items,
            disabled_packages=[
                str(item) for item in (raw.get("disabled_packages") or [])
            ],
            battery=dict(raw.get("battery") or {}),
            modified_settings=dict(raw.get("modified_settings") or {}),
        )


@dataclass(frozen=True)
class SnapshotDocument:
    schema_version: int = SCHEMA_VERSION
    created_at: str = field(default_factory=_now)
    devices: dict[str, DeviceSnapshot] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "devices": {
                serial: snapshot.to_dict()
                for serial, snapshot in self.devices.items()
            },
        }


def save_snapshot(document: SnapshotDocument, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    try:
        temp.write_text(
            json.dumps(document.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temp, target)
    finally:
        if temp.exists():
            try:
                temp.unlink()
            except OSError:
                pass
    return target


def load_snapshot(path: str | Path) -> SnapshotDocument:
    source = Path(path)
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SnapshotFormatError(f"无法读取快照文件: {exc}") from exc
    except ValueError as exc:
        raise SnapshotFormatError(f"快照文件不是有效 JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise SnapshotFormatError("快照根节点必须是对象")
    version = raw.get("schema_version")
    if version != SCHEMA_VERSION:
        raise SnapshotFormatError(f"不支持的快照版本: {version!r}")
    raw_devices = raw.get("devices")
    if not isinstance(raw_devices, dict):
        raise SnapshotFormatError("快照 devices 必须是对象")
    devices: dict[str, DeviceSnapshot] = {}
    for serial, value in raw_devices.items():
        snapshot = DeviceSnapshot.from_dict(value)
        if snapshot.serial != str(serial):
            raise SnapshotFormatError(
                f"快照键与设备序列号不一致: {serial!r} != {snapshot.serial!r}"
            )
        devices[str(serial)] = snapshot
    return SnapshotDocument(
        schema_version=SCHEMA_VERSION,
        created_at=str(raw.get("created_at") or ""),
        devices=devices,
    )


__all__ = [
    "DeviceSnapshot",
    "SCHEMA_VERSION",
    "SnapshotDocument",
    "SnapshotFormatError",
    "SnapshotItem",
    "load_snapshot",
    "save_snapshot",
]
