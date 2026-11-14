from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, Signal


@dataclass(frozen=True)
class ProcessResult:
    ok: bool
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    cancelled: bool = False
    args: tuple[str, ...] = ()


class AdbProcess(QObject):
    """One asynchronous QProcess invocation.

    The process is never waited for on the UI thread. Callers observe the
    ``finished`` signal; ``output`` is emitted incrementally as text arrives.
    """

    output = Signal(str)
    error_output = Signal(str)
    finished = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._process: QProcess | None = None
        self._timer: QTimer | None = None
        self._stdout: list[str] = []
        self._stderr: list[str] = []
        self._timed_out = False
        self._cancelled = False
        self._emitted = False
        self._args: tuple[str, ...] = ()
        self._stdout_file: Path | None = None

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.state() != QProcess.NotRunning

    def run(
        self,
        argv: list[str],
        timeout_ms: int = 30000,
        stdout_file: Path | str | None = None,
    ) -> None:
        if not argv:
            raise ValueError("argv 不能为空")
        if self.is_running:
            raise RuntimeError("进程仍在运行")

        self._stdout.clear()
        self._stderr.clear()
        self._timed_out = False
        self._cancelled = False
        self._emitted = False
        self._args = tuple(argv)
        self._stdout_file = Path(stdout_file) if stdout_file is not None else None

        process = QProcess(self)
        process.setProgram(argv[0])
        process.setArguments(argv[1:])
        process.setProcessChannelMode(QProcess.SeparateChannels)
        if self._stdout_file is None:
            process.readyReadStandardOutput.connect(self._read_stdout)
        else:
            process.setStandardOutputFile(str(self._stdout_file))
        process.readyReadStandardError.connect(self._read_stderr)
        process.finished.connect(self._on_finished)
        process.errorOccurred.connect(self._on_error)
        self._process = process

        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(self._on_timeout)
        self._timer = timer
        if timeout_ms > 0:
            timer.start(timeout_ms)

        process.start()

    def cancel(self) -> None:
        if not self.is_running:
            return
        self._cancelled = True
        self._process.kill()

    def wait(self, timeout_ms: int = 1500) -> None:
        """Finish a cancelled process during window shutdown only."""
        if self._process is None:
            return
        if self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.waitForFinished(timeout_ms)
        if self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.kill()
            self._process.waitForFinished(500)
        if not self._emitted:
            self._finish(-1)

    def _read_stdout(self) -> None:
        if self._process is None or self._stdout_file is not None:
            return
        chunk = bytes(self._process.readAllStandardOutput()).decode("utf-8", "replace")
        if chunk:
            self._stdout.append(chunk)
            self.output.emit(chunk)

    def _read_stderr(self) -> None:
        if self._process is None:
            return
        chunk = bytes(self._process.readAllStandardError()).decode("utf-8", "replace")
        if chunk:
            self._stderr.append(chunk)
            self.error_output.emit(chunk)

    def _on_timeout(self) -> None:
        if not self.is_running:
            return
        self._timed_out = True
        self._process.kill()

    def _on_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.FailedToStart:
            self._finish(-1, extra_stderr=f"进程启动失败: {self._process.errorString()}")

    def _on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        self._read_stdout()
        self._read_stderr()
        if exit_status != QProcess.NormalExit:
            exit_code = -1
        self._finish(exit_code)

    def _finish(self, exit_code: int, extra_stderr: str = "") -> None:
        if self._emitted:
            return
        self._emitted = True
        if self._timer is not None:
            self._timer.stop()
        if extra_stderr:
            self._stderr.append(extra_stderr)
        result = ProcessResult(
            ok=exit_code == 0 and not self._timed_out and not self._cancelled,
            exit_code=exit_code,
            stdout="".join(self._stdout),
            stderr="".join(self._stderr),
            timed_out=self._timed_out,
            cancelled=self._cancelled,
            args=self._args,
        )
        self.finished.emit(result)
