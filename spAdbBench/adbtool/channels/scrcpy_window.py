from __future__ import annotations

import ctypes
import sys
from pathlib import Path

from PySide6.QtCore import (
    QObject,
    QProcess,
    QProcessEnvironment,
    QTimer,
    Signal,
)

WINDOW_TITLE_PREFIX = "手机控制 - "
# scrcpy must not be visible where the mouse can reach it before its first
# frame is ready: a mouse event before the content rectangle is initialized
# makes scrcpy divide by zero (0xC0000094).  Start it off-screen, then embed it
# only after the video texture has been created.
OFFSCREEN_X = -20000
OFFSCREEN_Y = -20000
READY_SETTLE_MS = 200


class ScrcpyWindowProcess(QObject):
    """Run the bundled official scrcpy as an independent native window.

    The embedded preview keeps using the in-process `wetest-scrcpy` channel, so
    opening this window never hides or minimizes the toolbox preview.
    """

    started = Signal()
    window_ready = Signal(int)
    failed = Signal(str)
    finished = Signal(int)
    log = Signal(str)

    def __init__(
        self,
        adb,
        executable: Path | str,
        parent: QObject | None = None,
        *,
        max_fps: int = 60,
        max_size: int = 1080,
    ) -> None:
        super().__init__(parent)
        self.adb = adb
        self.executable = Path(executable)
        self.max_fps = max(1, int(max_fps))
        self.max_size = max(0, int(max_size))
        self._process: QProcess | None = None
        self._serial = ""
        self._title = ""
        self._stopping = False
        self._hwnd = 0
        self._texture_ready = False
        self._ready_emitted = False
        self._log_tail = ""
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(100)
        self._poll_timer.timeout.connect(self._poll_window)
        self._ready_timer = QTimer(self)
        self._ready_timer.setSingleShot(True)
        self._ready_timer.setInterval(READY_SETTLE_MS)
        self._ready_timer.timeout.connect(self._emit_ready)

    @property
    def running(self) -> bool:
        return (
            self._process is not None
            and self._process.state() != QProcess.ProcessState.NotRunning
        )

    @property
    def window_title(self) -> str:
        return self._title

    @property
    def serial(self) -> str:
        return self._serial

    @property
    def hwnd(self) -> int:
        return self._hwnd

    @property
    def ready(self) -> bool:
        """True once the native window is found and its texture is ready."""
        return self._ready_emitted and not self._ready_timer.isActive()

    def build_args(self, serial: str, title: str | None = None) -> list[str]:
        title = title or f"{WINDOW_TITLE_PREFIX}{serial}"
        return [
            "--serial",
            serial,
            "--no-audio",
            "--max-fps",
            str(self.max_fps),
            "--max-size",
            str(self.max_size),
            "--window-title",
            title,
            "--window-x",
            str(OFFSCREEN_X),
            "--window-y",
            str(OFFSCREEN_Y),
            "--window-borderless",
            "--no-window-aspect-ratio-lock",
            "--pause-on-exit=false",
        ]

    def start(self, serial: str) -> bool:
        if self.running:
            if self.ready:
                self.activate()
            return True
        if not serial:
            self._fail("未选择设备")
            return False
        if not self.executable.is_file():
            self._fail(f"未找到官方 scrcpy：{self.executable}")
            return False
        server = self.executable.parent / "scrcpy-server"
        if not server.is_file():
            self._fail(f"未找到官方 scrcpy-server：{server}")
            return False

        self._serial = serial
        self._title = f"{WINDOW_TITLE_PREFIX}{serial}"
        self._stopping = False
        self._hwnd = 0
        self._texture_ready = False
        self._ready_emitted = False
        self._log_tail = ""
        self._ready_timer.stop()
        if self._process is not None:
            self._process.deleteLater()
            self._process = None
        process = self._create_process()
        process.setProgram(str(self.executable))
        process.setArguments(self.build_args(serial, self._title))
        process.setWorkingDirectory(str(self.executable.parent))
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("ADB", str(self.adb.adb_path))
        environment.insert("SCRCPY_SERVER_PATH", str(server))
        process.setProcessEnvironment(environment)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.start()
        self._poll_timer.start()
        return True

    def activate(self) -> None:
        if not self._title or sys.platform != "win32":
            return
        try:
            user32 = ctypes.windll.user32
            hwnd = self._find_window()
            if hwnd:
                user32.ShowWindow(hwnd, 9)
                user32.SetForegroundWindow(hwnd)
        except Exception:
            pass

    def _find_window(self) -> int:
        if not self._title or sys.platform != "win32":
            return 0
        try:
            return int(ctypes.windll.user32.FindWindowW(None, self._title) or 0)
        except Exception:
            return 0

    def _poll_window(self) -> None:
        if not self.running:
            self._poll_timer.stop()
            return
        hwnd = self._find_window()
        if hwnd:
            self._hwnd = hwnd
            self._schedule_ready()

    def _schedule_ready(self) -> None:
        if (
            self._ready_emitted
            or not self._texture_ready
            or not self._hwnd
            or not self.running
        ):
            return
        self._ready_emitted = True
        self._poll_timer.stop()
        self._ready_timer.start()

    def _emit_ready(self) -> None:
        if self._ready_emitted and self._hwnd and self.running:
            self.window_ready.emit(self._hwnd)

    def stop(self) -> None:
        self._stopping = True
        self._poll_timer.stop()
        self._ready_timer.stop()
        self._texture_ready = False
        self._ready_emitted = False
        process = self._process
        if process is None or process.state() == QProcess.ProcessState.NotRunning:
            self._process = None
            self._stopping = False
            self._hwnd = 0
            return
        if self._request_close() and process.waitForFinished(1500):
            self._process = None
            self._stopping = False
            self._hwnd = 0
            process.deleteLater()
            return
        process.terminate()
        if not process.waitForFinished(1500):
            process.kill()
            process.waitForFinished(500)
        self._process = None
        self._stopping = False
        self._hwnd = 0
        process.deleteLater()

    def _request_close(self) -> bool:
        hwnd = self._hwnd or self._find_window()
        if not hwnd:
            return False
        try:
            return bool(ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0))
        except Exception:
            return False

    def _create_process(self) -> QProcess:
        process = QProcess(self)
        process.started.connect(lambda p=process: self._on_started(p))
        process.finished.connect(
            lambda code, status, p=process: self._on_finished(p, code, status)
        )
        process.errorOccurred.connect(
            lambda error, p=process: self._on_error(p, error)
        )
        process.readyReadStandardOutput.connect(
            lambda p=process: self._read_log(p)
        )
        self._process = process
        return process

    def _on_started(self, process: QProcess) -> None:
        if process is not self._process:
            return
        self.started.emit()

    def _on_finished(
        self,
        process: QProcess,
        exit_code: int,
        _status: QProcess.ExitStatus,
    ) -> None:
        if process is not self._process:
            return
        self._read_log(process)
        self._poll_timer.stop()
        self._ready_timer.stop()
        self._process = None
        self._hwnd = 0
        self._texture_ready = False
        self._ready_emitted = False
        process.deleteLater()
        if not self._stopping:
            self.finished.emit(exit_code)
        self._stopping = False

    def _on_error(
        self,
        process: QProcess,
        error: QProcess.ProcessError,
    ) -> None:
        if process is not self._process:
            return
        if error == QProcess.ProcessError.FailedToStart:
            self._poll_timer.stop()
            self._ready_timer.stop()
            self._process = None
            self._hwnd = 0
            self._texture_ready = False
            self._ready_emitted = False
            process.deleteLater()
            self._fail(f"官方 scrcpy 启动失败：{process.errorString()}")

    def _read_log(self, process: QProcess) -> None:
        if process is not self._process:
            return
        text = bytes(process.readAllStandardOutput()).decode("utf-8", "replace")
        if not text:
            return
        self.log.emit(text)
        # Log reads may split a line, so keep a small tail and search across
        # chunk boundaries.
        self._log_tail = (self._log_tail + text)[-4096:]
        if "Texture:" in self._log_tail:
            self._texture_ready = True
            self._schedule_ready()

    def _fail(self, message: str) -> None:
        self.failed.emit(message)
