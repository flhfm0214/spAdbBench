from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from adbtool.infrastructure.config import AppConfig, ConfigStore
from adbtool.infrastructure.parsers import DeviceInfo
from adbtool.services.adb import AdbService
from adbtool.services.devices import DeviceService
from adbtool.ui.context import AppContext
from adbtool.ui.main_window import MainWindow
from adbtool.ui.pages.flash_page import FlashPage
from adbtool.ui.status_bus import StatusBus


def make_context(tmp_path, adb=None):
    config = AppConfig(adb_path=str(Path("platform-tools") / "adb.exe"))
    store = ConfigStore(tmp_path)
    service = adb or AdbService(Path(config.adb_path))
    devices = DeviceService(service)
    return AppContext(config, store, service, devices, StatusBus())


def make_page(qtbot, tmp_path, state="device"):
    page = FlashPage(make_context(tmp_path))
    qtbot.addWidget(page)
    page.on_device_changed(DeviceInfo(serial="ABC", state=state))
    return page


def test_unlock_is_disabled_in_adb_mode(qtbot, tmp_path):
    page = make_page(qtbot, tmp_path)

    assert page.unlock_command.text() == ""
    assert page.lock_command.text() == ""
    assert page.unlock_button.isEnabled() is False
    assert page.lock_button.isEnabled() is False
    assert page.reboot_buttons["bootloader"].isEnabled() is True


def test_unlock_and_lock_commands_use_fastboot(qtbot, tmp_path):
    page = make_page(qtbot, tmp_path, state="fastboot")

    assert page.unlock_command.text() == "fastboot -s ABC oem unlock"
    assert page.lock_command.text() == "fastboot -s ABC oem lock"
    assert page.unlock_button.isEnabled() is True
    assert page.lock_button.isEnabled() is True
    assert page.reboot_buttons["bootloader"].isEnabled() is False


def test_copy_unlock_command(qtbot, tmp_path):
    page = make_page(qtbot, tmp_path, state="fastboot")

    page.copy_unlock_button.click()

    assert QApplication.clipboard().text() == "fastboot -s ABC oem unlock"


def test_unlock_executes_through_fastboot(qtbot, tmp_path, monkeypatch):
    page = make_page(qtbot, tmp_path, state="fastboot")
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "adbtool.ui.pages.flash_page.confirm_danger",
        lambda *_args, **_kwargs: True,
    )
    page.fastboot_session.start = lambda serial, command: calls.append(
        (serial, command)
    )

    page.unlock_button.click()
    page.lock_button.click()

    assert calls == [("ABC", "oem unlock"), ("ABC", "oem lock")]


def test_unlock_buttons_do_nothing_in_adb_mode(qtbot, tmp_path):
    page = make_page(qtbot, tmp_path)
    calls: list[tuple[str, str]] = []
    page.fastboot_session.start = lambda serial, command: calls.append(
        (serial, command)
    )

    page.unlock_button.click()
    page.lock_button.click()

    assert calls == []


def test_image_command_is_generated_without_execution(qtbot, tmp_path):
    page = make_page(qtbot, tmp_path)
    calls = []
    page.context.adb.run = lambda *args, **kwargs: calls.append((args, kwargs))

    page.partition_combo.setCurrentText("boot")
    page.image_path.setText(r"C:\images\boot.img")

    assert page.flash_command.text() == 'fastboot flash boot "C:\\images\\boot.img"'
    assert page.copy_flash_button.isEnabled() is True
    assert calls == []


def test_reboot_uses_danger_confirmation(qtbot, tmp_path, monkeypatch):
    page = make_page(qtbot, tmp_path)
    seen = []

    def refuse(parent, spec):
        seen.append(spec)
        return False

    monkeypatch.setattr("adbtool.ui.pages.flash_page.confirm_danger", refuse)

    page.reboot_buttons["bootloader"].click()

    assert [spec.key for spec in seen] == ["reboot.bootloader"]
    assert "adb -s ABC reboot bootloader" in seen[0].command
    assert page._process is None


def test_repair_adb_runs_in_background(qtbot, tmp_path):
    page = make_page(qtbot, tmp_path)
    runs = []

    class Process(QObject):
        finished = Signal(object)

        def __init__(self):
            super().__init__()
            self.is_running = False

        def finish(self, ok=True):
            self.finished.emit(
                SimpleNamespace(ok=ok, stdout="started", stderr="", cancelled=False)
            )

    def run(serial, *args, **kwargs):
        process = Process()
        runs.append((serial, args))
        return process

    page.context.adb.run = run

    page.repair_button.click()

    assert runs == [(None, ("kill-server",))]
    assert page.repair_button.isEnabled() is False
    page._repair_job._process.finish(ok=True)
    assert runs[-1] == (None, ("start-server",))
    page._repair_job._process.finish(ok=True)
    assert page.repair_button.isEnabled() is True
    assert "已重启" in page.message_label.text()


def test_main_window_embeds_flash_page(qtbot, tmp_path):
    window = MainWindow(make_context(tmp_path), auto_refresh=False)
    qtbot.addWidget(window)

    assert isinstance(window.stack.widget(8), FlashPage)
    assert window.nav.item(8).text() == "刷机辅助"
    window.close()
