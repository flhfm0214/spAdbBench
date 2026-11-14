from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QPushButton

from adbtool.infrastructure.config import AppConfig, ConfigStore
from adbtool.infrastructure.process import ProcessResult
from adbtool.services.adb import AdbService
from adbtool.services.battery import BatteryService
from adbtool.services.devices import DeviceService
from adbtool.ui.context import AppContext
from adbtool.ui.main_window import MainWindow
from adbtool.ui.pages.battery_page import BatteryPage
from adbtool.ui.status_bus import StatusBus
from tests.test_battery import FakeAdb


def make_window(qtbot, tmp_path):
    config = AppConfig(adb_path=str(Path("platform-tools") / "adb.exe"))
    store = ConfigStore(tmp_path)
    adb = AdbService(Path(config.adb_path))
    devices = DeviceService(adb)
    context = AppContext(config, store, adb, devices, StatusBus())
    window = MainWindow(context, auto_refresh=False)
    qtbot.addWidget(window)
    return window, context


def prepare_page(page: BatteryPage, context):
    fake = FakeAdb()
    page.service = BatteryService(fake, context.battery_tracker)
    page._serial = "ABC"
    page._update_controls()
    return fake


def test_battery_page_is_seventh_navigation_page(qtbot, tmp_path):
    window, _context = make_window(qtbot, tmp_path)
    page = window.stack.widget(7)

    assert isinstance(page, BatteryPage)
    assert page.interval_spin.value() == 1
    assert window.nav.count() == 13


def test_level_apply_waits_for_confirmation(qtbot, tmp_path, monkeypatch):
    window, context = make_window(qtbot, tmp_path)
    page = window.stack.widget(7)
    fake = prepare_page(page, context)
    specs = []

    monkeypatch.setattr(page, "_confirm", lambda spec: specs.append(spec) or False)
    page.level_spin.setValue(55)
    page.apply_level.click()

    assert specs[-1].key == "battery.simulate"
    assert fake.shells == []

    monkeypatch.setattr(page, "_confirm", lambda _spec: True)
    page.apply_level.click()

    assert fake.shells[-1][1] == "dumpsys battery set level 55"


def test_info_updates_labels_and_raw_output(qtbot, tmp_path):
    window, context = make_window(qtbot, tmp_path)
    page = window.stack.widget(7)
    prepare_page(page, context)
    page._serial = "ABC"

    page._on_info_finished(
        "ABC",
        ProcessResult(
            ok=True,
            exit_code=0,
            stdout=(
                "level: 87\n"
                "temperature: 315\n"
                "voltage: 4301\n"
                "status: 2\n"
                "health: 2\n"
                "USB powered: true\n"
                "current now: -120000\n"
            ),
            stderr="",
        ),
    )

    assert page.level_value.text() == "87%"
    assert "31.5" in page.temperature_value.text()
    assert page.status_value.text() == "充电中"
    assert page.source_value.text() == "USB"
    assert "-120000" in page.current_value.text()
    assert "level: 87" in page.raw_output.toPlainText()


def test_battery_buttons_fit_at_minimum_width(qtbot, tmp_path):
    window, _context = make_window(qtbot, tmp_path)
    window.resize(980, 640)
    window.show()
    window.nav.setCurrentRow(7)
    qtbot.wait(30)
    page = window.stack.widget(7)

    for button in page.findChildren(QPushButton):
        if button.isVisible():
            assert button.width() >= button.sizeHint().width(), button.text()
