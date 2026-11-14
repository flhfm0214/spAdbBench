from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from adbtool.infrastructure.config import AppConfig, ConfigStore
from adbtool.infrastructure.process import ProcessResult
from adbtool.services.adb import AdbService
from adbtool.services.devices import DeviceService
from adbtool.ui.context import AppContext
from adbtool.ui.status_bus import StatusBus
from adbtool.ui.widgets.foreground_bar import ForegroundAppBar


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


class FakeForegroundService:
    def __init__(self) -> None:
        self.restarted: list[tuple[str, str]] = []

    def foreground(self, serial: str):
        output = (
            "mResumedActivity: ActivityRecord{123 u0 "
            "com.example.app/.MainActivity t42}\n"
        )
        return FakeProcess(ProcessResult(True, 0, output, ""))

    def restart(self, serial: str, package: str):
        self.restarted.append((serial, package))
        return FakeProcess(ProcessResult(True, 0, "", ""))


def make_bar(qtbot, tmp_path):
    config = AppConfig(adb_path=str(Path("platform-tools") / "adb.exe"))
    store = ConfigStore(tmp_path)
    adb = AdbService(Path(config.adb_path))
    devices = DeviceService(adb)
    context = AppContext(config, store, adb, devices, StatusBus())
    service = FakeForegroundService()
    bar = ForegroundAppBar(context, service=service)
    qtbot.addWidget(bar)
    return bar, service


def test_foreground_bar_reads_and_displays_foreground_app(qtbot, tmp_path):
    bar, _service = make_bar(qtbot, tmp_path)
    bar.set_serial("ABC")

    bar.refresh()

    qtbot.waitUntil(lambda: bar.package == "com.example.app", timeout=3000)
    assert bar.label.text() == "前台应用：com.example.app / .MainActivity"
    assert bar.restart_button.isEnabled() is True


def test_foreground_bar_restarts_foreground_app(qtbot, tmp_path):
    bar, service = make_bar(qtbot, tmp_path)
    bar.set_serial("ABC")
    bar.refresh()
    qtbot.waitUntil(lambda: bar.package == "com.example.app", timeout=3000)

    bar.restart_button.click()

    qtbot.waitUntil(lambda: bool(service.restarted), timeout=3000)
    assert service.restarted == [("ABC", "com.example.app")]


def test_foreground_bar_disables_restart_without_foreground(qtbot, tmp_path):
    bar, _service = make_bar(qtbot, tmp_path)

    assert bar.restart_button.isEnabled() is False
    bar.set_serial("ABC")
    assert bar.restart_button.isEnabled() is False
