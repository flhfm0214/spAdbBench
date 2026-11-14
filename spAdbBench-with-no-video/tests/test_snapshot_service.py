import json
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, QTimer, Signal

from adbtool.infrastructure.process import ProcessResult
from adbtool.services.battery_state import BatterySimulationTracker
from adbtool.services.settings_history import SettingsHistoryStore
from adbtool.services.snapshot import (
    CompareRow,
    SnapshotDeviceMismatch,
    SnapshotItem,
    SnapshotService,
)
from adbtool.services.snapshot_files import (
    DeviceSnapshot,
    SnapshotDocument,
    load_snapshot,
    save_snapshot,
)
from adbtool.services.snapshot_registry import SNAPSHOT_FIELDS


class FakeProcess(QObject):
    finished = Signal(object)

    def __init__(self, result: ProcessResult, parent=None) -> None:
        super().__init__(parent)
        self._result = result
        self.is_running = True
        QTimer.singleShot(0, self._finish)

    def _finish(self) -> None:
        self.is_running = False
        self.finished.emit(self._result)

    def cancel(self) -> None:
        self.is_running = False


class FakeAdb:
    def __init__(self, responses: dict[str, str], failures: set[str] | None = None):
        self.responses = responses
        self.failures = failures or set()
        self.commands: list[str] = []

    def shell(self, serial: str, command: str, timeout_ms: int = 30000):
        self.commands.append(command)
        if command in self.failures:
            return FakeProcess(ProcessResult(False, 1, "", "read failed"))
        return FakeProcess(ProcessResult(True, 0, self.responses.get(command, ""), ""))


def make_service(tmp_path, responses, failures=None):
    adb = FakeAdb(responses, failures)
    history = SettingsHistoryStore(tmp_path / "history.json")
    tracker = BatterySimulationTracker(tmp_path / "battery.json")
    service = SnapshotService(adb, SNAPSHOT_FIELDS, history, tracker)
    return service, adb, history, tracker


def make_item(key: str, value: str | None = None) -> SnapshotItem:
    field = next(item for item in SNAPSHOT_FIELDS if item.key == key)
    return SnapshotItem(
        key=field.key,
        label=field.label,
        group=field.group,
        value=value,
        read_command=field.read_command,
        write_command=field.write_command,
        kind=field.kind,
        reset_command=field.reset_command,
        quote_value=field.quote_value,
    )


def make_snapshot(serial: str = "ABC", items=None) -> DeviceSnapshot:
    return DeviceSnapshot(
        serial=serial,
        model="Pixel 7",
        captured_at="2026-11-14T03:00:00+08:00",
        items=items or {"display.size": make_item("display.size", "1080x2400")},
    )


def test_snapshot_document_contains_commands(tmp_path):
    doc = SnapshotDocument(devices={"ABC": make_snapshot("ABC")})
    path = tmp_path / "snap.json"

    save_snapshot(doc, path)

    raw = json.loads(path.read_text(encoding="utf-8"))
    item = raw["devices"]["ABC"]["items"]["display.size"]
    assert item["read_command"] == "wm size"
    assert item["write_command"] == "wm size {value}"
    assert raw["devices"]["ABC"]["serial"] == "ABC"


def test_snapshot_document_roundtrip(tmp_path):
    doc = SnapshotDocument(devices={"ABC": make_snapshot("ABC")})
    path = tmp_path / "snap.json"

    save_snapshot(doc, path)
    loaded = load_snapshot(path)

    assert loaded == doc


def test_compare_marks_unavailable_when_current_read_fails(qtbot, tmp_path):
    service, _adb, _history, _tracker = make_service(tmp_path, {})
    item = make_item("system.font_scale", "1.15")
    snapshot = make_snapshot(items={item.key: item})
    _adb.failures.add(item.read_command)
    rows: list[CompareRow] = []
    job = service.compare("ABC", snapshot)
    job.finished.connect(rows.append)

    job.start()

    qtbot.waitUntil(lambda: bool(rows), timeout=3000)
    row = rows[0][0]
    assert row.available is False
    assert row.status == "不可用"


def test_compare_reports_changed_and_same_values(qtbot, tmp_path):
    font = make_item("system.font_scale", "1.15")
    size = make_item("display.size", "1080x2400")
    responses = {
        font.read_command: "1.0\n",
        size.read_command: "Physical size: 1080x2400\nOverride size: 1080x2400\n",
    }
    service, _adb, _history, _tracker = make_service(tmp_path, responses)
    snapshot = make_snapshot(items={font.key: font, size.key: size})
    rows: list[CompareRow] = []
    job = service.compare("ABC", snapshot)
    job.finished.connect(rows.append)

    job.start()

    qtbot.waitUntil(lambda: bool(rows), timeout=3000)
    by_key = {row.key: row for row in rows[0]}
    assert by_key[font.key].available is True
    assert by_key[font.key].same is False
    assert by_key[font.key].status == "不同"
    assert by_key[size.key].same is True
    assert by_key[size.key].status == "一致"


def test_compare_rejects_snapshot_for_other_device(tmp_path):
    service, _adb, _history, _tracker = make_service(tmp_path, {})

    with pytest.raises(SnapshotDeviceMismatch):
        service.compare("XYZ", make_snapshot("ABC"))


def test_rollback_skips_unavailable_and_quotes_values(qtbot, tmp_path):
    service, adb, _history, _tracker = make_service(tmp_path, {})
    available = CompareRow(
        key="system.font_scale",
        label="字体倍率",
        group="显示与动画",
        current="1.0",
        desired="1.0'; reboot; #",
        available=True,
        same=False,
        read_command="settings get system font_scale",
        write_command="settings put system font_scale {value}",
        kind="float",
    )
    unavailable = CompareRow(
        key="global.policy_control",
        label="沉浸模式",
        group="显示与动画",
        current=None,
        desired="null",
        available=False,
        same=False,
        read_command="settings get global policy_control",
        write_command="settings put global policy_control {value}",
        kind="raw",
    )
    results: list[object] = []
    item_events: list[tuple] = []
    job = service.rollback("ABC", [available, unavailable])
    job.finished.connect(results.append)
    job.item_finished.connect(lambda *args: item_events.append(args))

    job.start()

    qtbot.waitUntil(lambda: bool(results), timeout=3000)
    assert results[0][0].ok is True
    assert results[0][1].skipped is True
    assert "不可用" in results[0][1].message
    assert adb.commands == [
        "settings put system font_scale '1.0'\\''; reboot; #'"
    ]
    assert item_events[1][1] is False


def test_rollback_battery_simulation_runs_set_commands(qtbot, tmp_path):
    service, adb, _history, _tracker = make_service(tmp_path, {})
    item = make_item(
        "battery.simulation",
        json.dumps(
            {
                "level": 50,
                "temperature_c": 30.0,
                "status": 2,
                "unplugged": False,
                "usb": True,
            }
        ),
    )
    results: list[object] = []
    job = service.rollback("ABC", [item])
    job.finished.connect(results.append)

    job.start()

    qtbot.waitUntil(lambda: bool(results), timeout=3000)
    assert results[0][0].ok is True
    assert adb.commands[0] == "dumpsys battery reset"
    assert "dumpsys battery set level 50" in adb.commands
    assert "dumpsys battery set temp 300" in adb.commands
    assert "dumpsys battery set status 2" in adb.commands
    assert "dumpsys battery set usb 1" in adb.commands


def test_rollback_continues_after_one_item_fails(qtbot, tmp_path):
    service, adb, _history, _tracker = make_service(tmp_path, {})
    first = CompareRow(
        key="system.font_scale",
        label="字体倍率",
        group="显示与动画",
        current="1.0",
        desired="1.1",
        available=True,
        same=False,
        read_command="settings get system font_scale",
        write_command="settings put system font_scale {value}",
        kind="float",
    )
    second = CompareRow(
        key="global.policy_control",
        label="沉浸模式",
        group="显示与动画",
        current="null",
        desired="null",
        available=True,
        same=False,
        read_command="settings get global policy_control",
        write_command="settings put global policy_control {value}",
        kind="raw",
    )
    original_shell = adb.shell

    def shell(serial, command, timeout_ms=30000):
        if "font_scale" in command:
            adb.commands.append(command)
            return FakeProcess(ProcessResult(False, 1, "", "write failed"))
        return original_shell(serial, command, timeout_ms=timeout_ms)

    adb.shell = shell
    results: list[object] = []
    job = service.rollback("ABC", [first, second])
    job.finished.connect(results.append)

    job.start()

    qtbot.waitUntil(lambda: bool(results), timeout=3000)
    assert results[0][0].ok is False
    assert results[0][1].ok is True
    assert results[0][1].key == "global.policy_control"


def test_capture_keeps_going_when_one_field_fails(qtbot, tmp_path):
    responses = {
        "getprop ro.product.model": "Pixel 7\n",
        "wm size": "Physical size: 1080x2400\nOverride size: 1080x2400\n",
        "wm density": "Physical density: 420\nOverride density: 440\n",
        "settings get system font_scale": "1.0\n",
        "settings get global window_animation_scale": "1.0\n",
        "settings get global transition_animation_scale": "1.0\n",
        "settings get global animator_duration_scale": "1.0\n",
        "settings get system screen_off_timeout": "60000\n",
        "settings get global policy_control": "null\n",
        "settings get secure icon_blacklist": "null\n",
        "pm list packages -d": "",
        "dumpsys battery": "",
    }
    service, adb, _history, _tracker = make_service(
        tmp_path,
        responses,
        failures={"settings get system font_scale"},
    )
    snapshots: list[DeviceSnapshot] = []
    job = service.capture("ABC")
    job.finished.connect(snapshots.append)

    job.start()

    qtbot.waitUntil(lambda: bool(snapshots), timeout=5000)
    snapshot = snapshots[0]
    assert snapshot.items["system.font_scale"].captured_ok is False
    assert snapshot.items["display.size"].captured_ok is True
    assert len(snapshot.items) == len(SNAPSHOT_FIELDS)


def test_capture_reads_model_fields_history_and_battery(qtbot, tmp_path):
    history = SettingsHistoryStore(tmp_path / "history.json")
    history.record(
        "ABC",
        "system",
        "font_scale",
        "1.15",
        "settings put system font_scale '1.15'",
    )
    responses = {
        "getprop ro.product.model": "Pixel 7\n",
        "wm size": "Physical size: 1080x2400\nOverride size: 1080x2400\n",
        "wm density": "Physical density: 420\nOverride density: 440\n",
        "settings get system font_scale": "1.15\n",
        "settings get global window_animation_scale": "1.0\n",
        "settings get global transition_animation_scale": "0.5\n",
        "settings get global animator_duration_scale": "0.5\n",
        "settings get system screen_off_timeout": "60000\n",
        "settings get global policy_control": "null\n",
        "settings get secure icon_blacklist": "clock,alarm\n",
        "pm list packages -d": "package:com.example.disabled\n",
        "dumpsys battery": "level: 50\n",
    }
    service, adb, _history, tracker = make_service(tmp_path, responses)
    service.history = history
    tracker.mark("ABC", {"level": 50, "unplugged": False})
    snapshots: list[DeviceSnapshot] = []
    progress: list[tuple] = []
    job = service.capture("ABC")
    job.finished.connect(snapshots.append)
    job.progress.connect(lambda *args: progress.append(args))

    job.start()

    qtbot.waitUntil(lambda: bool(snapshots), timeout=5000)
    snapshot = snapshots[0]
    assert snapshot.serial == "ABC"
    assert snapshot.model == "Pixel 7"
    assert snapshot.items["display.size"].value == "1080x2400"
    assert snapshot.items["display.density"].value == "440"
    assert snapshot.items["settings.system.font_scale"].value == "1.15"
    assert snapshot.disabled_packages == ["com.example.disabled"]
    assert snapshot.battery["state"]["level"] == 50
    assert snapshot.modified_settings["system.font_scale"] == "1.15"
    assert progress[-1][0] == progress[-1][1]
