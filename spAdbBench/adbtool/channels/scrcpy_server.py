from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal, Slot

REMOTE_SERVER_PATH = "/data/local/tmp/adbtool-scrcpy-server.jar"
SCRCPY_SERVER_VERSION = "1.2.4"
SOCKET_PREFIX = "ct-scrcpy"


class ScrcpyServerProcess(QObject):
    """Push and run the bundled scrcpy-server through adb/QProcess."""

    ready = Signal()
    log = Signal(str)
    failed = Signal(str)
    state = Signal(str)

    def __init__(
        self,
        adb,
        server_path: Path | str,
        parent: QObject | None = None,
        *,
        max_size: int = 1080,
        max_fps: int = 30,
        bit_rate: int = 8_000_000,
    ) -> None:
        super().__init__(parent)
        self.adb = adb
        self.server_path = Path(server_path)
        self.max_size = int(max_size)
        self.max_fps = int(max_fps)
        self.bit_rate = int(bit_rate)
        self._process: QProcess | None = None
        self._push = None
        self._serial = ""
        self._stopping = False
        self._wired = False
        self._recent_log: list[str] = []

    @property
    def process(self) -> QProcess:
        if self._process is None:
            self._process = QProcess(self)
        return self._process

    def build_server_argv(self, serial: str) -> list[str]:
        return self.adb.build(serial, "shell", self.server_command())

    def server_command(self) -> str:
        return " ".join(
            [
                f"CLASSPATH={REMOTE_SERVER_PATH}",
                "app_process",
                "/",
                "com.genymobile.scrcpy.Server",
                SCRCPY_SERVER_VERSION,
                f"max_size={self.max_size}",
                f"bit_rate={self.bit_rate}",
                f"max_fps={self.max_fps}",
                "tunnel_forward=true",
                f"udt_socket_name={SOCKET_PREFIX}",
                "clipboard_autosync=false",
                "audio_codec=raw",
            ]
        )

    def start(self, serial: str) -> None:
        if self._process is not None and self._process.state() != QProcess.NotRunning:
            self.ready.emit()
            return
        self._serial = serial
        self._stopping = False
        if not self.server_path.is_file():
            self._fail(f"scrcpy-server 不存在：{self.server_path}")
            return

        self.state.emit("推送中")
        try:
            self._push = self.adb.run(
                serial,
                "push",
                str(self.server_path),
                REMOTE_SERVER_PATH,
                timeout_ms=30000,
                record=False,
            )
        except Exception as exc:
            self._fail(f"推送 scrcpy-server 失败：{exc}")
            return
        self._push.finished.connect(self._on_push_finished)

    @Slot(object)
    def _on_push_finished(self, result) -> None:
        self._push = None
        if self._stopping:
            return
        if not getattr(result, "ok", False):
            message = (
                getattr(result, "stderr", "").strip()
                or getattr(result, "stdout", "").strip()
                or "未知错误"
            )
            self._fail(f"推送 scrcpy-server 失败：{message}")
            return
        self._start_app_process()

    def _start_app_process(self) -> None:
        process = self.process
        if process.state() != QProcess.NotRunning:
            process.kill()
            process.waitForFinished(500)
        argv = self.build_server_argv(self._serial)
        process.setProgram(argv[0])
        process.setArguments(argv[1:])
        process.setProcessChannelMode(QProcess.SeparateChannels)
        if not self._wired:
            process.readyReadStandardOutput.connect(self._read_stdout)
            process.readyReadStandardError.connect(self._read_stderr)
            process.started.connect(self._on_started)
            process.finished.connect(self._on_finished)
            process.errorOccurred.connect(self._on_error)
            self._wired = True
        self.state.emit("启动中")
        process.start()

    @Slot()
    def _on_started(self) -> None:
        self.state.emit("运行中")
        self.ready.emit()

    @Slot(int, QProcess.ExitStatus)
    def _on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        self._read_stdout()
        self._read_stderr()
        if self._stopping:
            return
        tail = "".join(self._recent_log[-4:]).strip()
        detail = f"：{tail}" if tail else ""
        self._fail(f"scrcpy-server 已退出（{exit_code}）{detail}")

    def _on_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self._fail(f"scrcpy-server 启动失败：{self.process.errorString()}")

    @Slot()
    def _read_stdout(self) -> None:
        if self._process is None:
            return
        self._emit_log(bytes(self._process.readAllStandardOutput()).decode("utf-8", "replace"))

    @Slot()
    def _read_stderr(self) -> None:
        if self._process is None:
            return
        self._emit_log(bytes(self._process.readAllStandardError()).decode("utf-8", "replace"))

    def _emit_log(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        self._recent_log.extend(text.splitlines())
        self._recent_log = self._recent_log[-20:]
        self.log.emit(text)

    def _fail(self, message: str) -> None:
        if self._stopping:
            return
        self.state.emit("错误")
        self.failed.emit(message)

    def stop(self) -> None:
        self._stopping = True
        if self._push is not None:
            cancel = getattr(self._push, "cancel", None)
            if callable(cancel):
                try:
                    cancel()
                except Exception:
                    pass
            self._push = None
        process = self._process
        if process is not None and process.state() != QProcess.NotRunning:
            process.kill()
            process.waitForFinished(800)
        self.state.emit("已停止")
