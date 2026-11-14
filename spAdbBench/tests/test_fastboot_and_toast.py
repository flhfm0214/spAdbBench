from pathlib import Path

from PySide6.QtWidgets import QLabel

from adbtool.infrastructure.config import AppConfig, ConfigStore
from adbtool.infrastructure.parsers import DeviceInfo
from adbtool.services.adb import AdbService
from adbtool.services.devices import DeviceService
from adbtool.services.fastboot import (
    FastbootDevice,
    parse_fastboot_devices,
)
from adbtool.services.terminal import command_specs
from adbtool.ui.context import AppContext
from adbtool.ui.main_window import MainWindow
from adbtool.ui.pages.terminal_page import TerminalPage
from adbtool.ui.status_bus import StatusBus
from adbtool.ui.widgets.terminal_guide import GUIDE_ITEMS, TerminalGuideDialog
from adbtool.ui.widgets.toast import ToastBanner


def make_context(tmp_path):
    config = AppConfig(adb_path=str(Path("platform-tools") / "adb.exe"))
    store = ConfigStore(tmp_path)
    adb = AdbService(Path(config.adb_path))
    status = StatusBus()
    return AppContext(config, store, adb, DeviceService(adb), status)


def test_parse_fastboot_devices():
    text = (
        "3632ff7d\tfastboot usb:1-1\n"
        "emulator-5554\tfastboot\n"
        "broken offline\n"
        "\n"
    )
    devices = parse_fastboot_devices(text)

    assert [device.serial for device in devices] == ["3632ff7d", "emulator-5554"]
    assert devices[0].detail == "usb:1-1"


def test_fastboot_commands_are_in_catalog():
    layers = {spec.layer for spec in command_specs()}
    names = {spec.name for spec in command_specs() if spec.layer == "Fastboot"}

    assert "Fastboot" in layers
    assert {"flash", "getvar", "reboot", "devices"} <= names


def test_terminal_fastboot_mode_available_without_device(qtbot, tmp_path):
    page = TerminalPage(make_context(tmp_path))
    qtbot.addWidget(page)

    index = page.mode_combo.findData("fastboot")
    item = page.mode_combo.model().item(index)
    assert item.isEnabled() is True

    page.mode_combo.setCurrentIndex(index)
    assert page.mode == "fastboot"
    assert page.terminal.prompt == "fastboot> "
    assert page.state_label.text() == "等待 fastboot 设备"
    assert not page.device_hint.isHidden()
    assert page.device_hint.text().startswith("等待设备连接")

    page._on_fastboot_devices([FastbootDevice("fastboot-serial")])

    assert page.mode == "fastboot"
    assert page.device_hint.isHidden()
    assert page.state_label.text() == "Fastboot 就绪"

    page._on_fastboot_devices([])
    assert page.mode == "adb"
    assert not page.device_hint.isHidden()


def test_new_device_shows_in_window_toast(qtbot, tmp_path):
    window = MainWindow(make_context(tmp_path), auto_refresh=False)
    qtbot.addWidget(window)
    window.show()

    window._on_devices_changed([])
    window._on_devices_changed(
        [DeviceInfo(serial="R58M1234", state="offline", model="Pixel 8")]
    )

    assert window.toast.isVisible()
    assert "Pixel 8（USB）" in window.toast.detail_label.text()
    window.toast.close_button.click()
    qtbot.wait(260)
    assert window.toast.isHidden()


def test_fastboot_device_appears_in_selector_and_toast(qtbot, tmp_path):
    window = MainWindow(make_context(tmp_path), auto_refresh=False)
    qtbot.addWidget(window)
    window.show()
    window._on_devices_changed([])
    window._on_fastboot_devices([])
    window._on_fastboot_devices([FastbootDevice("fb-serial")])

    assert window.toast.isVisible()
    assert "fb-serial（Fastboot）" in window.toast.detail_label.text()
    states = [
        window.device_combo.itemData(index)
        for index in range(window.device_combo.count())
    ]
    assert any(item and item.state == "fastboot" for item in states)


def test_toast_auto_hide_interval(qtbot):
    toast = ToastBanner()
    qtbot.addWidget(toast)
    toast.show_message("设备（无线）已连接", 2000)

    assert toast.detail_label.text() == "设备（无线）已连接"
    assert toast.timer.isActive()
    assert toast.timer.interval() == 2000


def test_terminal_keeps_history_and_adds_exit_separator(qtbot, tmp_path):
    page = TerminalPage(make_context(tmp_path))
    qtbot.addWidget(page)
    page._load_packages = lambda: None
    page.on_device_changed(DeviceInfo("ABC", "device", model="Pixel 8"))
    page.terminal.append_output("hello output\n")
    page.terminal.flush_output()

    page.on_device_changed(None)

    text = page.terminal.toPlainText()
    assert "hello output" in text
    assert "----------" in text
    assert "Pixel 8已退出-----------" in text

    page.mode_combo.setCurrentIndex(page.mode_combo.findData("shell"))
    page.mode_combo.setCurrentIndex(page.mode_combo.findData("adb"))
    text = page.terminal.toPlainText()
    assert "hello output" in text
    assert "Pixel 8已退出-----------" in text


def test_terminal_guide_is_shortcut_only(qtbot, tmp_path):
    page = TerminalPage(make_context(tmp_path))
    qtbot.addWidget(page)
    assert not hasattr(page, "guide_button")
    assert page.guide_shortcut.key().toString() == "F1"

    dialog = TerminalGuideDialog(page)
    qtbot.addWidget(dialog)
    assert dialog.list.count() == len(GUIDE_ITEMS)
    first = dialog.list.itemWidget(dialog.list.item(0))
    assert "ADB 模式" in {label.text() for label in first.findChildren(QLabel)}
