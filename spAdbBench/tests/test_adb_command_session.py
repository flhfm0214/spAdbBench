from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from adbtool.infrastructure.process import ProcessResult
from adbtool.services.terminal import AdbCommandSession, split_adb_command


class FakeProcess(QObject):
    output = Signal(str)
    error_output = Signal(str)
    finished = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.cancelled = False

    @property
    def is_running(self) -> bool:
        return not self.cancelled

    def cancel(self) -> None:
        self.cancelled = True


class FakeAdb:
    adb_path = Path("adb.exe")

    def __init__(self) -> None:
        self.argv = []
        self.timeout_ms = None
        self.process = FakeProcess()

    def build(self, serial, *args):
        return [str(self.adb_path), "-s", serial, *args]

    def run_argv(self, argv, timeout_ms=0, record=True):
        self.argv = argv
        self.timeout_ms = timeout_ms
        return self.process


def test_split_adb_command_preserves_quoted_windows_path():
    assert split_adb_command('install -r "C:\\Program Files\\app.apk"') == [
        "install",
        "-r",
        "C:\\Program Files\\app.apk",
    ]


def test_adb_session_strips_adb_prefix_and_runs_selected_serial():
    adb = FakeAdb()
    session = AdbCommandSession(adb)
    states = []
    session.state.connect(states.append)

    session.start("ABC", "adb devices")

    assert adb.argv == ["adb.exe", "-s", "ABC", "devices"]
    assert adb.timeout_ms == 0
    assert states == ["执行中…"]


def test_adb_session_streams_output_and_finishes():
    adb = FakeAdb()
    session = AdbCommandSession(adb)
    output = []
    results = []
    session.output.connect(output.append)
    session.finished.connect(results.append)
    session.start("ABC", "devices")

    adb.process.output.emit("List of devices attached\n")
    adb.process.finished.emit(
        ProcessResult(ok=True, exit_code=0, stdout="", stderr="")
    )

    assert output == ["List of devices attached\n"]
    assert results[0].ok is True
    assert session.running is False


def test_adb_session_rejects_empty_command():
    adb = FakeAdb()
    session = AdbCommandSession(adb)
    errors = []
    session.error.connect(errors.append)

    session.start("ABC", "adb")

    assert errors == ["请输入 ADB 命令"]
    assert adb.argv == []
