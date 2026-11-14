from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Signal

from adbtool.infrastructure.process import ProcessResult
from adbtool.services.settings import SettingsService
from adbtool.services.settings_history import SettingsHistoryStore


class FakeProcess(QObject):
    finished = Signal(object)

    def __init__(self, argv: list[str]) -> None:
        super().__init__()
        self.argv = tuple(argv)
        self.is_running = True
        self.cancelled = False

    def complete(
        self,
        *,
        ok: bool = True,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self.is_running = False
        self.finished.emit(
            ProcessResult(
                ok=ok,
                exit_code=0 if ok else 1,
                stdout=stdout,
                stderr=stderr,
                args=self.argv,
            )
        )

    def cancel(self) -> None:
        self.cancelled = True
        self.is_running = False


class FakeAdb:
    def __init__(self) -> None:
        self.shells: list[tuple[str, str, FakeProcess]] = []

    def shell(self, serial, script, timeout_ms=30000, record=True):
        process = FakeProcess([serial, script])
        self.shells.append((serial, script, process))
        return process


def make_service(tmp_path):
    adb = FakeAdb()
    history = SettingsHistoryStore(tmp_path / "data" / "settings_history.json")
    return SettingsService(adb, history), adb, history


def test_get_builds_read_command(tmp_path):
    service, adb, _history = make_service(tmp_path)

    service.get("ABC", "system", "font_scale")
    service.get("ABC", "secure", "icon_blacklist")

    assert [entry[1] for entry in adb.shells] == [
        "settings get system font_scale",
        "settings get secure icon_blacklist",
    ]


def test_put_quotes_value_and_records_only_success(tmp_path):
    service, adb, history = make_service(tmp_path)

    failed = service.put("ABC", "secure", "icon_blacklist", "clock,alarm")
    assert adb.shells[0][1] == (
        "settings put secure icon_blacklist 'clock,alarm'"
    )
    assert history.entries("ABC") == []

    failed.complete(ok=False, stderr="denied")
    assert history.entries("ABC") == []

    success = service.put("ABC", "secure", "icon_blacklist", "clock,alarm")
    success.complete()
    entries = history.entries("ABC")
    assert len(entries) == 1
    assert entries[0].value == "clock,alarm"
    assert entries[0].write_command == (
        "settings put secure icon_blacklist 'clock,alarm'"
    )


def test_put_escapes_single_quote_without_changing_command_structure(tmp_path):
    service, adb, history = make_service(tmp_path)

    process = service.put("ABC", "system", "demo", "a'b; reboot")
    script = adb.shells[0][1]

    assert script == "settings put system demo 'a'\\''b; reboot'"
    process.complete()
    assert history.entries("ABC")[0].value == "a'b; reboot"


@pytest.mark.parametrize("table", ["danger", "", "system; reboot"])
def test_invalid_table_rejected_before_process(tmp_path, table):
    service, adb, _history = make_service(tmp_path)

    with pytest.raises(ValueError):
        service.put("ABC", table, "key", "value")

    assert adb.shells == []


@pytest.mark.parametrize("value", ["", "a\nb", "a\x00b"])
def test_invalid_value_rejected_before_process(tmp_path, value):
    service, adb, _history = make_service(tmp_path)

    with pytest.raises(ValueError):
        service.put("ABC", "system", "key", value)

    assert adb.shells == []


@pytest.mark.parametrize("key", ["", "a b", "a;b", "x\ny"])
def test_invalid_key_rejected_before_process(tmp_path, key):
    service, adb, _history = make_service(tmp_path)

    with pytest.raises(ValueError):
        service.get("ABC", "system", key)

    assert adb.shells == []


def test_icon_blacklist_empty_writes_null(tmp_path):
    service, adb, history = make_service(tmp_path)

    process = service.set_icon_blacklist("ABC", [])
    assert adb.shells[0][1] == "settings put secure icon_blacklist 'null'"

    process.complete()
    assert history.entries("ABC")[0].value == "null"


def test_screen_timeout_accepts_zero_and_65535(tmp_path):
    service, adb, _history = make_service(tmp_path)

    service.set_screen_timeout("ABC", 0)
    service.set_screen_timeout("ABC", 65535)

    assert adb.shells[0][1] == "settings put system screen_off_timeout '0'"
    assert adb.shells[1][1] == (
        "settings put system screen_off_timeout '65535000'"
    )
    with pytest.raises(ValueError):
        service.set_screen_timeout("ABC", 65536)


def test_font_scale_and_animation_validation(tmp_path):
    service, _adb, _history = make_service(tmp_path)

    with pytest.raises(ValueError):
        service.set_font_scale("ABC", 0.49)
    with pytest.raises(ValueError):
        service.set_animation_scale("ABC", "window_animation_scale", 11)

    service.set_font_scale("ABC", 1.15)
    service.set_animation_scale("ABC", "window_animation_scale", 0)

    assert "settings put system font_scale '1.15'" in service.adb.shells[0][1]
    assert "settings put global window_animation_scale '0'" in (
        service.adb.shells[1][1]
    )


def test_history_store_persists_and_replaces_same_key(tmp_path):
    path = tmp_path / "history.json"
    store = SettingsHistoryStore(path)
    store.record("ABC", "system", "font_scale", "1.0", "settings put system font_scale '1.0'")
    store.record("ABC", "system", "font_scale", "1.2", "settings put system font_scale '1.2'")
    store.record("XYZ", "secure", "icon_blacklist", "clock", "settings put secure icon_blacklist 'clock'")

    reloaded = SettingsHistoryStore(path)
    entries = reloaded.entries("ABC")

    assert len(entries) == 1
    assert entries[0].value == "1.2"
    assert len(reloaded.entries("XYZ")) == 1


def test_history_store_survives_corrupt_file(tmp_path):
    path = tmp_path / "history.json"
    path.write_text("{not json", encoding="utf-8")

    store = SettingsHistoryStore(path)

    assert store.entries("ABC") == []
