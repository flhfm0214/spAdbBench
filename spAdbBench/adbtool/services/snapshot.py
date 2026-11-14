from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime

from PySide6.QtCore import QObject, Signal

from ..infrastructure.parsers import parse_wm_density, parse_wm_size
from ..infrastructure.validation import validate_int, validate_number, validate_package
from .snapshot_files import DeviceSnapshot, SnapshotItem
from .snapshot_registry import (
    SNAPSHOT_FIELDS,
    SnapshotField,
    build_dynamic_settings_fields,
    render_write,
)


_DISPLAY_SIZE_RE = re.compile(r"^\d{2,5}x\d{2,5}$")


class SnapshotDeviceMismatch(ValueError):
    pass


@dataclass(frozen=True)
class CompareRow:
    key: str
    label: str
    group: str
    current: str | None
    desired: str | None
    available: bool
    same: bool
    read_command: str
    write_command: str
    kind: str
    reset_command: str = ""
    quote_value: bool = True
    item: SnapshotItem | None = field(default=None, compare=False, repr=False)

    @property
    def status(self) -> str:
        if not self.available:
            return "不可用"
        return "一致" if self.same else "不同"


@dataclass(frozen=True)
class RollbackResult:
    key: str
    label: str
    ok: bool
    skipped: bool
    message: str


def parse_disabled_packages(text: str) -> list[str]:
    packages: list[str] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("package:"):
            line = line[len("package:") :].strip()
        if line and line not in packages:
            packages.append(line)
    return packages


def normalize_value(key: str, raw: str, kind: str = "raw") -> str | None:
    text = (raw or "").strip()
    if key == "display.size":
        if "Override size:" not in text:
            return None
        effective, _physical = parse_wm_size(text)
        return effective
    if key == "display.density":
        if "Override density:" not in text:
            return None
        override, _physical = parse_wm_density(text)
        return str(override) if override is not None else None
    if key == "packages.disabled":
        return "\n".join(parse_disabled_packages(text))
    if not text:
        return None
    if kind in {"int", "float"} and text.lower() in {"null", "none"}:
        return None
    return text


def _field_missing(field: SnapshotField | None, raw: str) -> bool:
    if field is None or field.unavailable_when is None:
        return False
    return field.unavailable_when(raw)


def _item_field(item: SnapshotItem) -> SnapshotField:
    return SnapshotField(
        key=item.key,
        label=item.label,
        group=item.group,
        read_command=item.read_command,
        write_command=item.write_command,
        kind=item.kind,
        reset_command=item.reset_command,
        quote_value=item.quote_value,
    )


def _battery_commands(value: str | None) -> list[str]:
    commands = ["dumpsys battery reset"]
    if not value:
        return commands
    try:
        state = json.loads(value)
    except ValueError as exc:
        raise ValueError("电池模拟快照不是有效 JSON") from exc
    if not isinstance(state, dict) or not state:
        return commands

    if state.get("unplugged"):
        commands.append("dumpsys battery unplug")
    else:
        for source in ("ac", "usb", "wireless"):
            if source in state:
                commands.append(
                    f"dumpsys battery set {source} "
                    f"{1 if state[source] else 0}"
                )
    if "level" in state:
        level = validate_int(state["level"], 0, 100, "电量")
        commands.append(f"dumpsys battery set level {level}")
    if "temperature_c" in state:
        temperature = validate_number(state["temperature_c"], -20, 100, "温度")
        commands.append(f"dumpsys battery set temp {int(round(temperature * 10))}")
    if "status" in state:
        status = validate_int(state["status"], 1, 5, "电池状态")
        commands.append(f"dumpsys battery set status {status}")
    return commands


def _packages_commands(current: str | None, desired: str | None) -> list[str]:
    current_packages = set(parse_disabled_packages(current or ""))
    desired_packages = set(parse_disabled_packages(desired or ""))
    commands: list[str] = []
    for package in sorted(desired_packages - current_packages):
        package = validate_package(package)
        commands.append(f"pm disable-user --user 0 {package}")
    for package in sorted(current_packages - desired_packages):
        package = validate_package(package)
        commands.append(f"pm enable {package}")
    return commands


def _rollback_commands(row: CompareRow) -> list[str]:
    if row.key == "battery.simulation":
        return _battery_commands(row.desired)
    if row.key == "packages.disabled":
        return _packages_commands(row.current, row.desired)
    field = SnapshotField(
        key=row.key,
        label=row.label,
        group=row.group,
        read_command=row.read_command,
        write_command=row.write_command,
        kind=row.kind,
        reset_command=row.reset_command,
        quote_value=row.quote_value,
    )
    if row.key == "display.size" and row.desired is not None:
        if not _DISPLAY_SIZE_RE.fullmatch(row.desired):
            raise ValueError(f"分辨率格式不合法: {row.desired!r}")
    if row.key == "display.density" and row.desired is not None:
        validate_int(row.desired, 72, 1000, "DPI")
    return [render_write(field, row.desired)]


class SnapshotCaptureJob(QObject):
    progress = Signal(int, int, str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, service, serial: str, fields: list[SnapshotField], parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.serial = serial
        self.fields = list(fields)
        self._total = len(self.fields) + 1
        self._done = 0
        self._index = 0
        self._items: dict[str, SnapshotItem] = {}
        self._model = ""
        self._disabled: list[str] = []
        self._battery: dict = {"state": {}, "raw": ""}
        self._process = None
        self._cancelled = False
        self._finished = False
        self._modified = {
            f"{entry.table}.{entry.key}": entry.value
            for entry in service.history.entries(serial)
        }

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def start(self) -> None:
        if not self.serial:
            self.failed.emit("请先连接设备")
            return
        self.progress.emit(0, self._total, "读取设备型号")
        process = self.service.adb.shell(
            self.serial,
            "getprop ro.product.model",
            timeout_ms=15000,
        )
        self._process = process
        process.finished.connect(self._on_model)

    def cancel(self) -> None:
        if self._finished:
            return
        self._cancelled = True
        if self._process is not None and self._process.is_running:
            self._process.cancel()
        self._finish()

    def _on_model(self, result) -> None:
        if self._finished:
            return
        self._process = None
        if self._cancelled:
            self._finish()
            return
        if result.ok:
            self._model = result.stdout.strip()
        self._done = 1
        self.progress.emit(self._done, self._total, "读取设备型号")
        self._read_next()

    def _read_next(self) -> None:
        if self._cancelled or self._index >= len(self.fields):
            self._finish()
            return
        field = self.fields[self._index]
        self.progress.emit(self._done, self._total, field.label)
        process = self.service.adb.shell(
            self.serial,
            field.read_command,
            timeout_ms=30000,
        )
        self._process = process
        process.finished.connect(self._on_field)

    def _on_field(self, result) -> None:
        if self._finished:
            return
        self._process = None
        if self._cancelled:
            self._finish()
            return
        field = self.fields[self._index]
        raw = result.stdout if result.ok else ""
        error = ""
        if not result.ok:
            error = (result.stderr or result.stdout).strip() or "读取失败"
        available = result.ok and not _field_missing(field, raw)

        if field.key == "battery.simulation":
            state = self.service.battery_tracker.state(self.serial) or {}
            value = json.dumps(state, ensure_ascii=False, sort_keys=True) if state else None
            self._battery = {"state": state, "raw": raw}
        else:
            value = normalize_value(field.key, raw, field.kind)
            if field.key == "packages.disabled":
                self._disabled = parse_disabled_packages(raw)

        self._items[field.key] = SnapshotItem(
            key=field.key,
            label=field.label,
            group=field.group,
            value=value,
            read_command=field.read_command,
            write_command=field.write_command,
            kind=field.kind,
            captured_ok=available,
            error=error,
            reset_command=field.reset_command,
            quote_value=field.quote_value,
        )
        self._index += 1
        self._done += 1
        self._read_next()

    def _finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        if not self._cancelled:
            self.progress.emit(self._done, self._total, "完成")
        snapshot = DeviceSnapshot(
            serial=self.serial,
            model=self._model,
            captured_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            items=dict(self._items),
            disabled_packages=list(self._disabled),
            battery=dict(self._battery),
            modified_settings=dict(self._modified),
        )
        self.finished.emit(snapshot)


class SnapshotCompareJob(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, service, serial: str, snapshot: DeviceSnapshot, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.serial = serial
        self.snapshot = snapshot
        self._items = list(snapshot.items.values())
        self._index = 0
        self._rows: list[CompareRow] = []
        self._process = None
        self._finished = False
        self._cancelled = False

    def start(self) -> None:
        self._run_next()

    def cancel(self) -> None:
        if self._finished:
            return
        self._cancelled = True
        if self._process is not None and self._process.is_running:
            self._process.cancel()
        self._finish()

    def _run_next(self) -> None:
        if self._cancelled:
            self._finish()
            return
        if self._index >= len(self._items):
            self._finish()
            return
        item = self._items[self._index]
        process = self.service.adb.shell(
            self.serial,
            item.read_command,
            timeout_ms=30000,
        )
        self._process = process
        process.finished.connect(self._on_read)

    def _on_read(self, result) -> None:
        if self._finished:
            return
        self._process = None
        if self._cancelled:
            self._finish()
            return
        item = self._items[self._index]
        field = self.service.field_for(item.key)
        raw = result.stdout if result.ok else ""
        if item.key == "battery.simulation":
            state = self.service.battery_tracker.state(self.serial) or {}
            current = json.dumps(state, ensure_ascii=False, sort_keys=True) if state else None
        else:
            current = normalize_value(item.key, raw, item.kind)
        available = bool(
            result.ok
            and item.captured_ok
            and not _field_missing(field, raw)
        )
        self._rows.append(
            CompareRow(
                key=item.key,
                label=item.label,
                group=item.group,
                current=current,
                desired=item.value,
                available=available,
                same=available and current == item.value,
                read_command=item.read_command,
                write_command=item.write_command,
                kind=item.kind,
                reset_command=item.reset_command,
                quote_value=item.quote_value,
                item=item,
            )
        )
        self._index += 1
        self._run_next()

    def _finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        self.finished.emit(list(self._rows))


class RollbackJob(QObject):
    item_finished = Signal(object, bool, str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, service, serial: str, items: list, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.serial = serial
        self._rows = [self._as_row(item) for item in items]
        self._index = 0
        self._results: list[RollbackResult] = []
        self._current_row: CompareRow | None = None
        self._commands: list[str] = []
        self._command_index = 0
        self._outputs: list[str] = []
        self._process = None
        self._finished = False
        self._cancelled = False

    @staticmethod
    def _as_row(item) -> CompareRow:
        if isinstance(item, CompareRow):
            return item
        if isinstance(item, SnapshotItem):
            return CompareRow(
                key=item.key,
                label=item.label,
                group=item.group,
                current=None,
                desired=item.value,
                available=item.captured_ok,
                same=False,
                read_command=item.read_command,
                write_command=item.write_command,
                kind=item.kind,
                reset_command=item.reset_command,
                quote_value=item.quote_value,
                item=item,
            )
        raise TypeError(f"不支持的回滚项: {type(item).__name__}")

    def start(self) -> None:
        if not self.serial:
            self.failed.emit("请先连接设备")
            return
        self._run_next()

    def cancel(self) -> None:
        if self._finished:
            return
        self._cancelled = True
        if self._process is not None and self._process.is_running:
            self._process.cancel()
        self._finish()

    def _run_next(self) -> None:
        if self._cancelled:
            self._finish()
            return
        if self._index >= len(self._rows):
            self._finish()
            return
        row = self._rows[self._index]
        self._current_row = row
        if not row.available:
            self._finish_item(False, "不可用，已跳过", skipped=True)
            return
        try:
            commands = _rollback_commands(row)
        except (ValueError, TypeError) as exc:
            self._finish_item(False, str(exc), skipped=False)
            return
        if not commands:
            self._finish_item(True, "无需修改", skipped=False)
            return
        self._commands = commands
        self._command_index = 0
        self._outputs = []
        self._run_command()

    def _run_command(self) -> None:
        if self._command_index >= len(self._commands):
            self._finish_item(True, "\n".join(p for p in self._outputs if p), skipped=False)
            return
        command = self._commands[self._command_index]
        process = self.service.adb.shell(self.serial, command, timeout_ms=30000)
        self._process = process
        process.finished.connect(self._on_command)

    def _on_command(self, result) -> None:
        if self._finished:
            return
        self._process = None
        if self._cancelled:
            self._finish()
            return
        output = (result.stdout or result.stderr).strip()
        if output:
            self._outputs.append(output)
        if not result.ok:
            self._finish_item(False, output or "写入失败", skipped=False)
            return
        self._command_index += 1
        self._run_command()

    def _finish_item(self, ok: bool, message: str, skipped: bool) -> None:
        row = self._current_row
        if row is None:
            self._finish()
            return
        self._results.append(
            RollbackResult(
                key=row.key,
                label=row.label,
                ok=ok,
                skipped=skipped,
                message=message,
            )
        )
        self.item_finished.emit(row, ok, message)
        self._index += 1
        self._current_row = None
        self._run_next()

    def _finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        self.finished.emit(list(self._results))


class SnapshotService:
    def __init__(self, adb, registry, history, battery_tracker) -> None:
        self.adb = adb
        self.registry = list(registry)
        self.history = history
        self.battery_tracker = battery_tracker

    def fields_for(self, serial: str) -> list[SnapshotField]:
        return self.registry + build_dynamic_settings_fields(self.history.entries(serial))

    def field_for(self, key: str) -> SnapshotField | None:
        for field in self.registry:
            if field.key == key:
                return field
        return None

    def capture(self, serial: str) -> SnapshotCaptureJob:
        return SnapshotCaptureJob(self, serial, self.fields_for(serial))

    def compare(self, serial: str, snapshot: DeviceSnapshot) -> SnapshotCompareJob:
        if snapshot.serial != serial:
            raise SnapshotDeviceMismatch(
                f"快照属于设备 {snapshot.serial!r}，当前设备是 {serial!r}"
            )
        return SnapshotCompareJob(self, serial, snapshot)

    def rollback(self, serial: str, items: list) -> RollbackJob:
        return RollbackJob(self, serial, items)


__all__ = [
    "CompareRow",
    "RollbackJob",
    "RollbackResult",
    "SNAPSHOT_FIELDS",
    "SnapshotCaptureJob",
    "SnapshotCompareJob",
    "SnapshotDeviceMismatch",
    "SnapshotItem",
    "SnapshotService",
    "normalize_value",
    "parse_disabled_packages",
]
