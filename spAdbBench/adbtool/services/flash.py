from __future__ import annotations

import re
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from ..infrastructure.validation import validate_serial


PARTITION_RE = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")


@dataclass(frozen=True)
class RebootMode:
    mode: str
    label: str
    danger_key: str
    args: tuple[str, ...] = ()
    note: str = ""


REBOOT_MODES: dict[str, RebootMode] = {
    "system": RebootMode("system", "重启系统", "reboot.system"),
    "bootloader": RebootMode(
        "bootloader",
        "重启到 Bootloader",
        "reboot.bootloader",
        ("bootloader",),
        "设备进入 Bootloader/Fastboot 模式，ADB 连接会中断。",
    ),
    "recovery": RebootMode(
        "recovery",
        "重启到 Recovery",
        "reboot.recovery",
        ("recovery",),
        "设备进入 Recovery 模式，ADB 连接会中断。",
    ),
    "edl": RebootMode(
        "edl",
        "重启到 EDL",
        "reboot.edl",
        ("edl",),
        "仅部分机型支持 EDL/9008；进入后 ADB 会断开。",
    ),
    "fastboot": RebootMode(
        "fastboot",
        "重启到 Fastbootd",
        "reboot.fastbootd",
        ("fastboot",),
        "设备进入 Fastbootd 模式，ADB 连接会中断。",
    ),
}


class AdbRepairJob(QObject):
    """先结束 ADB server，再重新启动；两步都在后台执行。"""

    finished = Signal(object)

    def __init__(self, service: "FlashService", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self._process = None
        self._cancelled = False
        self._done = False

    def start(self) -> None:
        if self._done:
            return
        process = self.service.kill_server()
        self._process = process
        process.finished.connect(self._on_kill_finished)

    def cancel(self) -> None:
        if self._done:
            return
        self._cancelled = True
        process = self._process
        if process is not None and getattr(process, "is_running", False):
            process.cancel()

    def _on_kill_finished(self, result) -> None:
        if self._cancelled or self._done:
            return
        if not getattr(result, "ok", False):
            self._done = True
            self.finished.emit(result)
            return
        process = self.service.start_server()
        self._process = process
        process.finished.connect(self._on_start_finished)

    def _on_start_finished(self, result) -> None:
        if self._cancelled or self._done:
            return
        self._done = True
        self.finished.emit(result)


class FlashService:
    def __init__(self, adb) -> None:
        self.adb = adb

    def reboot(self, serial: str, mode: str = "system"):
        try:
            spec = REBOOT_MODES[mode]
        except KeyError as exc:
            raise ValueError(f"不支持的重启模式: {mode!r}") from exc
        device = validate_serial(serial)
        return self.adb.run(
            device,
            "reboot",
            *spec.args,
            timeout_ms=15000,
        )

    def reboot_command(self, serial: str, mode: str = "system") -> str:
        try:
            spec = REBOOT_MODES[mode]
        except KeyError as exc:
            raise ValueError(f"不支持的重启模式: {mode!r}") from exc
        command = f"adb -s {validate_serial(serial)} reboot"
        if spec.args:
            command += " " + " ".join(spec.args)
        return command

    def unlock_command(self, serial: str) -> str:
        return f"fastboot -s {validate_serial(serial)} oem unlock"

    def lock_command(self, serial: str) -> str:
        return f"fastboot -s {validate_serial(serial)} oem lock"

    def fastboot_flash_command(self, partition: str, image_path: str) -> str:
        name = (partition or "").strip()
        if not PARTITION_RE.fullmatch(name):
            raise ValueError(f"分区名不合法: {partition!r}")
        path = str(image_path or "").strip()
        if not path:
            raise ValueError("请选择镜像文件")
        if any(char in path for char in ('"', "\n", "\r", "\x00")):
            raise ValueError("镜像路径包含不支持的字符")
        return f'fastboot flash {name} "{path}"'

    def repair_adb(self) -> AdbRepairJob:
        return AdbRepairJob(self)

    def kill_server(self):
        return self.adb.run(None, "kill-server", timeout_ms=15000)

    def start_server(self):
        return self.adb.run(None, "start-server", timeout_ms=30000)

    def reconnect_offline(self):
        return self.adb.run(None, "reconnect", "offline", timeout_ms=15000)

    def version(self):
        return self.adb.run(None, "version", timeout_ms=15000)


__all__ = [
    "AdbRepairJob",
    "FlashService",
    "PARTITION_RE",
    "REBOOT_MODES",
    "RebootMode",
]
