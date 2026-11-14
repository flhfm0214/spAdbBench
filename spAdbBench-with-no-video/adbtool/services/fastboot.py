from __future__ import annotations

import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, Signal


def _split_command(command: str) -> list[str]:
    lexer = shlex.shlex(command or "", posix=False)
    lexer.whitespace_split = True
    lexer.commenters = ""
    tokens: list[str] = []
    for token in lexer:
        if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
            token = token[1:-1]
        if token:
            tokens.append(token)
    return tokens


FASTBOOT_COMMANDS = (
    "devices",
    "getvar",
    "flash",
    "flashall",
    "erase",
    "format",
    "reboot",
    "reboot-bootloader",
    "boot",
    "continue",
    "oem",
    "flashing",
    "unlock",
    "locking",
    "set_active",
    "fetch",
    "stage",
    "get_staged",
    "download",
    "dump",
    "resize",
    "wipe",
    "create-logical-partition",
    "delete-logical-partition",
    "snapshot-update",
    "help",
    "version",
)


FASTBOOT_HELP = {
    "devices": ("fastboot devices [-l]", "列出 fastboot 设备"),
    "getvar": ("fastboot getvar <变量>", "读取 bootloader 变量"),
    "flash": ("fastboot flash <分区> <镜像>", "刷写分区镜像"),
    "flashall": ("fastboot flashall [-w]", "刷写全部分区"),
    "erase": ("fastboot erase <分区>", "擦除分区"),
    "format": ("fastboot format <分区>", "格式化分区"),
    "reboot": ("fastboot reboot [bootloader|recovery]", "重启设备或切换模式"),
    "reboot-bootloader": ("fastboot reboot-bootloader", "重启到 bootloader"),
    "boot": ("fastboot boot <镜像>", "临时引导镜像"),
    "continue": ("fastboot continue", "继续启动系统"),
    "oem": ("fastboot oem <命令>", "执行厂商 OEM 命令"),
    "flashing": ("fastboot flashing <unlock|lock>", "解锁或锁定 bootloader"),
    "unlock": ("fastboot flashing unlock", "解锁 bootloader"),
    "locking": ("fastboot flashing lock", "锁定 bootloader"),
    "set_active": ("fastboot set_active <槽位>", "切换 A/B 槽位"),
    "fetch": ("fastboot fetch <分区> <文件>", "从设备取回分区"),
    "stage": ("fastboot stage <文件>", "暂存镜像到设备"),
    "get_staged": ("fastboot get_staged <文件>", "读取暂存镜像"),
    "download": ("fastboot download <文件>", "下载镜像到设备"),
    "dump": ("fastboot dump <分区>", "导出分区内容"),
    "resize": ("fastboot resize <分区>", "调整逻辑分区大小"),
    "wipe": ("fastboot wipe <分区>", "擦除逻辑分区"),
    "create-logical-partition": (
        "fastboot create-logical-partition <名称> <大小>",
        "创建逻辑分区",
    ),
    "delete-logical-partition": (
        "fastboot delete-logical-partition <名称>",
        "删除逻辑分区",
    ),
    "snapshot-update": ("fastboot snapshot-update <cancel|merge>", "处理快照更新"),
    "help": ("fastboot help", "显示 fastboot 帮助"),
    "version": ("fastboot version", "显示 fastboot 版本"),
}


@dataclass(frozen=True)
class FastbootDevice:
    serial: str
    detail: str = ""

    @property
    def display_name(self) -> str:
        return self.serial


def resolve_fastboot(adb_path: Path | str) -> Path:
    adb = Path(adb_path)
    sibling = adb.with_name("fastboot.exe" if adb.suffix.lower() == ".exe" else "fastboot")
    if sibling.is_file():
        return sibling
    found = shutil.which("fastboot")
    return Path(found) if found else sibling


def parse_fastboot_devices(text: str) -> list[FastbootDevice]:
    devices: list[FastbootDevice] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("List of devices"):
            continue
        parts = line.split()
        if len(parts) < 2 or parts[1] != "fastboot":
            continue
        detail = " ".join(parts[2:])
        devices.append(FastbootDevice(serial=parts[0], detail=detail))
    return devices


class FastbootService(QObject):
    devices_changed = Signal(object)
    failed = Signal(str)

    def __init__(self, adb, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.adb = adb
        self.fastboot_path = resolve_fastboot(adb.adb_path)
        self._busy = False
        self._process: QProcess | None = None
        self._timer: QTimer | None = None

    @property
    def busy(self) -> bool:
        return self._busy

    def refresh(self) -> None:
        if self._busy:
            return
        if not self.fastboot_path.is_file():
            self.devices_changed.emit([])
            return
        self._busy = True
        process = QProcess(self)
        self._process = process
        process.setProgram(str(self.fastboot_path))
        process.setArguments(["devices", "-l"])
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.finished.connect(
            lambda code, status, p=process: self._on_finished(p, code, status)
        )
        process.errorOccurred.connect(
            lambda error, p=process: self._on_error(p, error)
        )
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(6000)
        timer.timeout.connect(lambda p=process: self._timeout(p))
        self._timer = timer
        timer.start()
        process.start()

    def _on_finished(self, process: QProcess, code: int, status) -> None:
        if process is not self._process:
            return
        output = bytes(process.readAllStandardOutput()).decode("utf-8", "replace")
        self._finish()
        self.devices_changed.emit(parse_fastboot_devices(output))

    def _on_error(self, process: QProcess, error) -> None:
        if process is not self._process:
            return
        if error == QProcess.ProcessError.FailedToStart:
            message = process.errorString()
            self._finish()
            self.failed.emit(f"fastboot 启动失败：{message}")

    def _timeout(self, process: QProcess) -> None:
        if process is not self._process:
            return
        process.kill()
        self._finish()
        self.failed.emit("fastboot 设备检测超时")

    def _finish(self) -> None:
        self._busy = False
        if self._timer is not None:
            self._timer.stop()
            self._timer.deleteLater()
            self._timer = None
        process = self._process
        self._process = None
        if process is not None:
            process.deleteLater()

    def shutdown(self) -> None:
        if self._process is not None:
            self._process.kill()
            self._process.waitForFinished(500)
        self._finish()


class FastbootCommandSession(QObject):
    output = Signal(str)
    state = Signal(str)
    error = Signal(str)
    finished = Signal(object)

    def __init__(self, adb, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.fastboot_path = resolve_fastboot(adb.adb_path)
        self._serial = ""
        self._process: QProcess | None = None
        self._state = "空闲"

    @property
    def running(self) -> bool:
        return (
            self._process is not None
            and self._process.state() != QProcess.ProcessState.NotRunning
        )

    @property
    def serial(self) -> str:
        return self._serial

    def start(self, serial: str, command: str) -> None:
        self.stop()
        serial = (serial or "").strip()
        if not serial:
            self.error.emit("未连接 fastboot 设备")
            return
        if not self.fastboot_path.is_file():
            self.error.emit(f"未找到 fastboot：{self.fastboot_path}")
            return
        args = _split_command(command)
        if args and args[0].lower() == "fastboot":
            args = args[1:]
        if not args:
            self.error.emit("请输入 fastboot 命令")
            return
        self._serial = serial
        process = QProcess(self)
        process.setProgram(str(self.fastboot_path))
        process.setArguments(["-s", serial, *args])
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(
            lambda p=process: self._read(p)
        )
        process.finished.connect(
            lambda code, status, p=process: self._on_finished(p, code, status)
        )
        process.errorOccurred.connect(
            lambda error, p=process: self._on_error(p, error)
        )
        self._process = process
        self._set_state("执行中…")
        process.start()

    def _read(self, process: QProcess) -> None:
        if process is not self._process:
            return
        chunk = bytes(process.readAllStandardOutput()).decode("utf-8", "replace")
        if chunk:
            self.output.emit(chunk.replace("\r\n", "\n"))

    def _on_finished(self, process: QProcess, code: int, status) -> None:
        if process is not self._process:
            process.deleteLater()
            return
        self._read(process)
        self._process = None
        self._serial = ""
        self.finished.emit(process)
        if code == 0:
            self._set_state("已完成")
        else:
            self._set_state(f"执行失败（退出码 {code}）")

    def _on_error(self, process: QProcess, error) -> None:
        if process is not self._process:
            return
        if error == QProcess.ProcessError.FailedToStart:
            message = process.errorString()
            self._process = None
            self.error.emit(f"fastboot 启动失败：{message}")
            self._set_state("执行失败")

    def stop(self) -> None:
        process = self._process
        self._process = None
        self._serial = ""
        if process is not None:
            if process.state() != QProcess.ProcessState.NotRunning:
                process.kill()
                process.waitForFinished(500)
            process.deleteLater()
        self._set_state("已停止")

    def interrupt(self) -> None:
        self.stop()

    def wait(self, timeout_ms: int = 1500) -> None:
        process = self._process
        if process is not None and process.state() != QProcess.ProcessState.NotRunning:
            process.waitForFinished(timeout_ms)

    def _set_state(self, state: str) -> None:
        if state == self._state:
            return
        self._state = state
        self.state.emit(state)
