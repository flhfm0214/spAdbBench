from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from adbtool.infrastructure.process import ProcessResult
from adbtool.services.logcat import (
    LogcatSession,
    level_passes,
    parse_logcat_line,
)


LINE_INFO = "11-13 21:30:45.123  1234  5678 I ActivityManager: Start proc 1234"
LINE_ERROR = "11-13 21:30:46.456  1234  5678 E AndroidRuntime: FATAL EXCEPTION: main"
LINE_WARN = "11-13 21:30:47.789  2222  3333 W Choreographer: Skipped 42 frames"


def test_parse_logcat_line_reads_threadtime_fields():
    line = parse_logcat_line(LINE_INFO)

    assert line is not None
    assert line.timestamp == "11-13 21:30:45.123"
    assert line.pid == 1234
    assert line.tid == 5678
    assert line.level == "I"
    assert line.tag == "ActivityManager"
    assert line.message.startswith("Start proc 1234")
    assert line.raw == LINE_INFO


def test_parse_logcat_line_skips_buffer_headers_and_garbage():
    assert parse_logcat_line("--------- beginning of main") is None
    assert parse_logcat_line("not a logcat line") is None
    assert parse_logcat_line("") is None


def test_level_passes_uses_severity_order():
    assert level_passes("E", "W") is True
    assert level_passes("I", "W") is False
    assert level_passes("V", "V") is True
    assert level_passes("?", "V") is False


class FakeProcess(QObject):
    output = Signal(str)
    error_output = Signal(str)
    finished = Signal(object)

    def __init__(self, argv=None) -> None:
        super().__init__()
        self.argv = tuple(argv or ())
        self.is_running = True
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True
        self.is_running = False


class FakeAdb:
    def __init__(self) -> None:
        self.runs: list[FakeProcess] = []
        self.shells: list[tuple[str, str, FakeProcess]] = []

    def run(
        self,
        serial,
        *args,
        timeout_ms=30000,
        record=True,
        capture_output=True,
    ):
        process = FakeProcess([serial, *args])
        process.capture_output = capture_output
        self.runs.append(process)
        return process

    def shell(self, serial, script, timeout_ms=30000, record=True):
        process = FakeProcess([serial, script])
        self.shells.append((serial, script, process))
        return process


def test_session_starts_logcat_and_filters_level_and_keyword():
    adb = FakeAdb()
    session = LogcatSession(adb)
    lines = []
    session.line.connect(lines.append)

    session.start("ABC", level="W", keyword="")
    process = adb.runs[0]
    assert "-T" in process.argv
    assert "threadtime" in process.argv
    assert process.capture_output is False

    process.output.emit(f"{LINE_INFO}\n{LINE_ERROR}\n{LINE_WARN}\n")
    assert [line.level for line in lines] == ["E", "W"]

    session.set_filters(level="W", keyword="skipped")
    process.output.emit(f"{LINE_INFO}\n{LINE_WARN}\n")
    assert len(lines) == 3
    assert lines[-1].tag == "Choreographer"

    session.set_paused(True)
    session.set_filters(level="W", keyword="")
    process.output.emit(f"{LINE_ERROR}\n")
    assert len(lines) == 3
    session.set_paused(False)
    process.output.emit(f"{LINE_ERROR}\n")
    assert len(lines) == 4

    session.stop()
    assert process.cancelled is True


def test_session_ignores_output_after_stop():
    adb = FakeAdb()
    session = LogcatSession(adb)
    lines = []
    session.line.connect(lines.append)

    session.start("ABC", level="V")
    process = adb.runs[0]
    session.stop()
    process.output.emit(f"{LINE_INFO}\n")

    assert lines == []


def test_session_buffers_partial_chunks_and_flushes_on_stop():
    adb = FakeAdb()
    session = LogcatSession(adb)
    lines = []
    session.line.connect(lines.append)

    session.start("ABC", level="V")
    process = adb.runs[0]

    process.output.emit("11-13 21:30:45.123  1234  5678 I Tag")
    assert lines == []
    process.output.emit(": hello\n")
    assert len(lines) == 1
    assert lines[0].message == "hello"

    process.finished.emit(
        ProcessResult(ok=True, exit_code=0, stdout="", stderr="")
    )
    assert session.running is False


def test_session_resolves_package_pid_before_starting_logcat():
    adb = FakeAdb()
    session = LogcatSession(adb)
    session.start("ABC", level="V", package="com.example.app")

    assert adb.shells
    serial, script, pid_process = adb.shells[0]
    assert serial == "ABC"
    assert "pidof com.example.app" in script
    pid_process.finished.emit(
        ProcessResult(ok=True, exit_code=0, stdout="4321\n", stderr="")
    )

    assert adb.runs
    assert "--pid=4321" in adb.runs[0].argv

    session.stop()
