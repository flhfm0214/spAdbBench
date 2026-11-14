from __future__ import annotations

from pathlib import Path

from adbtool.infrastructure.config import AppConfig, ConfigStore
from adbtool.infrastructure.parsers import DeviceInfo
from adbtool.services.adb import AdbService
from adbtool.services.devices import DeviceService
from adbtool.services.logcat import LogLine
from adbtool.ui.context import AppContext
from adbtool.ui.main_window import MainWindow
from adbtool.ui.pages.logcat_page import LogcatPage
from adbtool.ui.status_bus import StatusBus


def make_window(qtbot, tmp_path):
    config = AppConfig(adb_path=str(Path("platform-tools") / "adb.exe"))
    store = ConfigStore(tmp_path)
    adb = AdbService(Path(config.adb_path))
    devices = DeviceService(adb)
    context = AppContext(config, store, adb, devices, StatusBus())
    window = MainWindow(context, auto_refresh=False)
    qtbot.addWidget(window)
    return window, context


def line(level="I", tag="Tag", message="hello") -> LogLine:
    return LogLine(
        timestamp="11-13 21:30:45.123",
        pid=1234,
        tid=5678,
        level=level,
        tag=tag,
        message=message,
        raw=f"11-13 21:30:45.123  1234  5678 {level} {tag}: {message}",
    )


def test_logcat_page_is_sixth_navigation_page(qtbot, tmp_path):
    window, _context = make_window(qtbot, tmp_path)

    assert isinstance(window.stack.widget(5), LogcatPage)


def test_logcat_page_controls_follow_device_and_filters_lines(qtbot, tmp_path):
    _window, context = make_window(qtbot, tmp_path)
    page = LogcatPage(context)
    qtbot.addWidget(page)
    page.on_device_changed(DeviceInfo(serial="ABC", state="device"))

    assert page.start_button.isEnabled() is True
    page.level_combo.setCurrentIndex(page.level_combo.findData("W"))

    page._on_line(line("I"))
    page._flush_pending()
    assert page.table.rowCount() == 0
    page._on_line(line("E", "AndroidRuntime", "FATAL EXCEPTION"))
    page._flush_pending()
    assert page.table.rowCount() == 1
    assert page.table.item(0, 1).text() == "E"
    assert page.table.item(0, 2).text() == "AndroidRuntime"
    assert "FATAL" in page.table.item(0, 3).text()

    page.keyword_edit.setText("not-present")
    page._on_line(line("E", "Other", "different"))
    page._flush_pending()
    assert page.table.rowCount() == 1

    page._toggle_pause()
    page._on_line(line("E", "AndroidRuntime", "FATAL EXCEPTION"))
    page._flush_pending()
    assert page.table.rowCount() == 1
    page._toggle_pause()

    page._clear()
    assert page.table.rowCount() == 0


def test_logcat_page_start_passes_filters_and_stops_on_device_change(
    qtbot, tmp_path, monkeypatch
):
    _window, context = make_window(qtbot, tmp_path)
    page = LogcatPage(context)
    qtbot.addWidget(page)
    page.on_device_changed(DeviceInfo(serial="ABC", state="device"))
    calls = []
    monkeypatch.setattr(
        page.session,
        "start",
        lambda serial, level, keyword, package: calls.append(
            (serial, level, keyword, package)
        ),
    )

    page.level_combo.setCurrentIndex(page.level_combo.findData("E"))
    page.keyword_edit.setText("crash")
    page.package_edit.setText("com.example.app")
    page.start_button.click()

    assert calls == [("ABC", "E", "crash", "com.example.app")]
    assert page.start_button.isEnabled() is False
    assert page.stop_button.isEnabled() is True

    page.on_device_changed(None)

    assert page.start_button.isEnabled() is False
    assert page.stop_button.isEnabled() is False
    assert page.table.rowCount() == 0


def test_logcat_page_pause_button_text_toggles(qtbot, tmp_path):
    _window, context = make_window(qtbot, tmp_path)
    page = LogcatPage(context)
    qtbot.addWidget(page)

    assert page.pause_button.text() == "暂停"
    page._toggle_pause()
    assert page.pause_button.text() == "继续"
    page._toggle_pause()
    assert page.pause_button.text() == "暂停"
