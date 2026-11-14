from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from adbtool.infrastructure.config import AppConfig, ConfigStore
from adbtool.infrastructure.parsers import DeviceInfo
from adbtool.infrastructure.process import ProcessResult
from adbtool.services.adb import AdbService
from adbtool.services.devices import DeviceService
from adbtool.services.display import DisplayInfo
from adbtool.ui.context import AppContext
from adbtool.ui.main_window import MainWindow
from adbtool.ui.pages.display_page import DisplayPage
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


def test_display_page_is_fourth_navigation_page(qtbot, tmp_path):
    window, _context = make_window(qtbot, tmp_path)
    assert isinstance(window.stack.widget(3), DisplayPage)


def test_display_page_controls_follow_device_state(qtbot, tmp_path):
    _window, context = make_window(qtbot, tmp_path)
    page = DisplayPage(context)
    qtbot.addWidget(page)

    assert page.set_size_button.isEnabled() is False
    assert page.key_buttons["home"].isEnabled() is False

    page.on_device_changed(DeviceInfo(serial="ABC", state="device"))

    assert page.set_size_button.isEnabled() is True
    assert page.key_buttons["home"].isEnabled() is True
    assert page.screenshot_path.text().endswith(".png")

    page.on_device_changed(None)

    assert page.set_size_button.isEnabled() is False
    assert page.key_buttons["home"].isEnabled() is False


def test_display_page_cancels_stale_info_on_device_switch(qtbot, tmp_path):
    _window, context = make_window(qtbot, tmp_path)
    page = DisplayPage(context)
    qtbot.addWidget(page)

    class FakeProcess:
        is_running = True

        def __init__(self):
            self.cancelled = False

        def cancel(self):
            self.cancelled = True

    fake = FakeProcess()
    page._serial = "OLD"
    page._info_process = fake

    page.on_device_changed(DeviceInfo(serial="NEW", state="device"))

    assert fake.cancelled is True
    assert page._info_process is None


def test_display_page_shows_captured_screenshot(qtbot, tmp_path):
    _window, context = make_window(qtbot, tmp_path)
    page = DisplayPage(context)
    qtbot.addWidget(page)
    page.on_device_changed(DeviceInfo(serial="ABC", state="device"))

    image_path = tmp_path / "shot.png"
    image = QImage(40, 20, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.blue)
    assert image.save(str(image_path)) is True

    page._on_screenshot_finished(
        "ABC",
        image_path,
        ProcessResult(ok=True, exit_code=0, stdout="", stderr=""),
    )

    assert page._last_screenshot == image_path
    assert page.preview.set_image(image_path) is True
    assert page.open_button.isEnabled() is True


def test_display_page_keeps_first_density_for_restore(qtbot, tmp_path):
    _window, context = make_window(qtbot, tmp_path)
    page = DisplayPage(context)
    qtbot.addWidget(page)
    page.on_device_changed(DeviceInfo(serial="ABC", state="device"))

    page._apply_info(
        DisplayInfo(
            effective_size="1080x2280",
            physical_size="1080x2280",
            effective_density=476,
            physical_density=560,
        )
    )
    page._apply_info(
        DisplayInfo(
            effective_size="1080x2280",
            physical_size="1080x2280",
            effective_density=420,
            physical_density=560,
        )
    )

    assert page._baseline_density == 476
    assert page._baseline_size == "1080x2280"
    assert page.reset_density_button.text() == "恢复初始 DPI"


def test_display_page_restores_initial_density(qtbot, tmp_path, monkeypatch):
    _window, context = make_window(qtbot, tmp_path)
    page = DisplayPage(context)
    qtbot.addWidget(page)
    page.on_device_changed(DeviceInfo(serial="ABC", state="device"))
    page._loaded_serial = "ABC"
    page._baseline_density = 476
    page._baseline_density_overridden = True
    calls = []

    def fake_set_density(serial, density):
        calls.append(("set", serial, density))
        return object()

    def fake_run_action(process, label, refresh=False):
        calls.append(("action", label, refresh))

    monkeypatch.setattr(page.service, "set_density", fake_set_density)
    monkeypatch.setattr(page, "_run_action", fake_run_action)

    page._restore_density()

    assert calls == [
        ("set", "ABC", 476),
        ("action", "恢复初始 DPI", True),
    ]


def test_display_page_uses_system_reset_without_initial_override(qtbot, tmp_path, monkeypatch):
    _window, context = make_window(qtbot, tmp_path)
    page = DisplayPage(context)
    qtbot.addWidget(page)
    page.on_device_changed(DeviceInfo(serial="ABC", state="device"))
    page._loaded_serial = "ABC"
    page._baseline_density = 560
    page._baseline_density_overridden = False
    calls = []

    def fake_reset_density(serial):
        calls.append(("reset", serial))
        return object()

    def fake_run_action(process, label, refresh=False):
        calls.append(("action", label, refresh))

    monkeypatch.setattr(page.service, "reset_density", fake_reset_density)
    monkeypatch.setattr(page, "_run_action", fake_run_action)

    page._restore_density()

    assert calls == [
        ("reset", "ABC"),
        ("action", "恢复初始 DPI", True),
    ]




