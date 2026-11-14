from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from ..infrastructure.parsers import DeviceInfo, parse_devices
from ..infrastructure.process import ProcessResult
from .adb import AdbService


class DeviceService(QObject):
    devices_changed = Signal(object)
    refresh_failed = Signal(str)
    refresh_started = Signal()

    def __init__(self, adb: AdbService, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.adb = adb
        self._busy = False
        self._last_devices: list[DeviceInfo] = []

    @property
    def devices(self) -> list[DeviceInfo]:
        return list(self._last_devices)

    @property
    def busy(self) -> bool:
        return self._busy

    def refresh(self, record: bool = True) -> None:
        if self._busy:
            return
        self._busy = True
        self.refresh_started.emit()
        process = self.adb.run(
            None,
            "devices",
            "-l",
            timeout_ms=15000,
            record=record,
        )
        process.finished.connect(self._on_finished)

    def _on_finished(self, result: ProcessResult) -> None:
        self._busy = False
        if not result.ok:
            message = result.stderr.strip() or result.stdout.strip() or "读取设备列表失败"
            self.refresh_failed.emit(message)
            return
        devices = parse_devices(result.stdout)
        self._last_devices = devices
        self.devices_changed.emit(devices)
