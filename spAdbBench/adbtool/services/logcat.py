from __future__ import annotations

import re
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from .adb import AdbService


LEVEL_ORDER = {
    "V": 0,
    "D": 1,
    "I": 2,
    "W": 3,
    "E": 4,
    "F": 5,
    "A": 6,
}

_THREADTIME_RE = re.compile(
    r"^(?P<date>\d{2}-\d{2})\s+(?P<time>\d{2}:\d{2}:\d{2}\.\d{3})\s+"
    r"(?P<pid>\d+)\s+(?P<tid>\d+)\s+(?P<level>[VDIWEFA])\s+"
    r"(?P<tag>.*?)\s*:\s?(?P<message>.*)$"
)

_PACKAGE_RE = re.compile(r"^[A-Za-z0-9_.]+$")


@dataclass(frozen=True)
class LogLine:
    timestamp: str
    pid: int
    tid: int
    level: str
    tag: str
    message: str
    raw: str


def parse_logcat_line(raw: str) -> LogLine | None:
    if not raw:
        return None
    match = _THREADTIME_RE.match(raw.strip())
    if not match:
        return None
    return LogLine(
        timestamp=f"{match.group('date')} {match.group('time')}",
        pid=int(match.group("pid")),
        tid=int(match.group("tid")),
        level=match.group("level"),
        tag=match.group("tag").strip(),
        message=match.group("message"),
        raw=raw,
    )


def level_passes(line_level: str, min_level: str) -> bool:
    line_rank = LEVEL_ORDER.get((line_level or "").upper())
    minimum = LEVEL_ORDER.get((min_level or "").upper())
    if line_rank is None or minimum is None:
        return False
    return line_rank >= minimum


class LogcatSession(QObject):
    line = Signal(object)
    state = Signal(str)
    error = Signal(str)

    def __init__(self, adb: AdbService, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.adb = adb
        self._serial = ""
        self._process = None
        self._pid_process = None
        self._buffer = ""
        self._running = False
        self._paused = False
        self._level = "V"
        self._keyword = ""
        self._package = ""

    @property
    def running(self) -> bool:
        return self._running

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def serial(self) -> str:
        return self._serial

    def start(
        self,
        serial: str,
        level: str = "V",
        keyword: str = "",
        package: str = "",
    ) -> None:
        self.stop()
        package = (package or "").strip()
        if package and not _PACKAGE_RE.fullmatch(package):
            self.error.emit("应用包名格式不正确")
            return
        self._serial = serial
        self._level = (level or "V").upper()
        self._keyword = (keyword or "").strip().lower()
        self._package = package
        self._buffer = ""
        self._paused = False
        if package:
            self.state.emit("正在定位应用进程…")
            process = self.adb.shell(
                serial,
                f"pidof {package}",
                timeout_ms=10000,
                record=False,
            )
            self._pid_process = process
            process.finished.connect(
                lambda result, s=serial, p=package: self._on_pid_finished(s, p, result)
            )
            return
        self._start_logcat(serial)

    def _on_pid_finished(self, serial: str, package: str, result) -> None:
        self._pid_process = None
        if serial != self._serial:
            return
        if result.cancelled:
            return
        if not result.ok:
            self._running = False
            self.state.emit("已停止")
            self.error.emit(
                (result.stderr or result.stdout).strip()
                or f"未找到 {package} 的进程"
            )
            return
        pid = ""
        for token in (result.stdout or "").split():
            if token.isdigit():
                pid = token
                break
        if not pid:
            self._running = False
            self.state.emit("已停止")
            self.error.emit(f"应用 {package} 未运行，无法过滤日志")
            return
        self._start_logcat(serial, pid)

    def _start_logcat(self, serial: str, pid: str = "") -> None:
        if serial != self._serial:
            return
        args = ["logcat", "-v", "threadtime", "-T", "1"]
        if pid:
            args.append(f"--pid={pid}")
        process = self.adb.run(
            serial,
            *args,
            timeout_ms=0,
            record=False,
        )
        self._process = process
        self._running = True
        process.output.connect(self._on_output)
        process.error_output.connect(self._on_error_output)
        process.finished.connect(
            lambda result, s=serial, p=process: self._on_finished(s, p, result)
        )
        self.state.emit("运行中")

    def stop(self) -> None:
        self._serial = ""
        self._running = False
        if self._pid_process is not None:
            process = self._pid_process
            self._pid_process = None
            process.cancel()
        if self._process is not None:
            process = self._process
            self._process = None
            process.cancel()
        self._buffer = ""
        self._paused = False
        self.state.emit("已停止")

    def set_filters(self, level: str, keyword: str = "") -> None:
        self._level = (level or "V").upper()
        self._keyword = (keyword or "").strip().lower()

    def set_paused(self, paused: bool) -> None:
        self._paused = bool(paused)
        if self._running:
            self.state.emit("已暂停" if self._paused else "运行中")

    def clear(self) -> None:
        self._buffer = ""

    def _on_output(self, chunk: str) -> None:
        if not chunk or not self._running:
            return
        self._buffer += chunk
        while "\n" in self._buffer:
            raw, self._buffer = self._buffer.split("\n", 1)
            self._handle_line(raw.rstrip("\r"))
        if len(self._buffer) > 1_000_000:
            self._buffer = self._buffer[-1_000_000:]

    def _on_error_output(self, chunk: str) -> None:
        message = (chunk or "").strip()
        if message:
            self.error.emit(message)

    def _handle_line(self, raw: str) -> None:
        line = parse_logcat_line(raw)
        if line is None:
            return
        if not level_passes(line.level, self._level):
            return
        if self._keyword and self._keyword not in raw.lower():
            return
        if self._paused:
            return
        self.line.emit(line)

    def _on_finished(self, serial: str, process, result) -> None:
        if process is not self._process:
            return
        self._process = None
        self._running = False
        if self._buffer:
            self._handle_line(self._buffer)
            self._buffer = ""
        if result.cancelled:
            self.state.emit("已停止")
            return
        if not result.ok:
            message = (result.stderr or result.stdout).strip() or "Logcat 已退出"
            self.error.emit(message)
        self.state.emit("已停止")
