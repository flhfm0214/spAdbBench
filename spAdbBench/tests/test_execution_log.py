from datetime import datetime
from pathlib import Path
import sys

from PySide6.QtTest import QSignalSpy

from adbtool.infrastructure.execution_log import (
    ExecutionLog,
    ExecutionRecord,
    serial_from_argv,
)
from adbtool.infrastructure.process import ProcessResult
from adbtool.services.adb import AdbService


def make_record(**overrides) -> ExecutionRecord:
    data = {
        "started_at": "2026-11-13T21:00:00+08:00",
        "serial": "ABC",
        "command": "adb.exe -s ABC shell wm density",
        "argv": ("adb.exe", "-s", "ABC", "shell", "wm density"),
        "ok": False,
        "exit_code": 1,
        "duration_ms": 123,
        "stdout": "Physical density: 450",
        "stderr": "error",
        "cancelled": False,
        "timed_out": False,
    }
    data.update(overrides)
    return ExecutionRecord(**data)


def test_serial_from_argv():
    assert serial_from_argv(["adb.exe", "-s", "ABC", "shell", "wm", "size"]) == "ABC"
    assert serial_from_argv(["adb.exe", "devices"]) == ""


def test_record_from_process_keeps_command_and_result():
    record = ExecutionRecord.from_process(
        ["adb.exe", "-s", "ABC", "shell", "wm", "density"],
        ProcessResult(
            ok=False,
            exit_code=1,
            stdout="Physical density: 450",
            stderr="error",
        ),
        datetime(2026, 11, 13, 21, 0, 0).astimezone(),
        duration_ms=123,
    )

    assert record.serial == "ABC"
    assert "shell wm density" in record.command
    assert record.result_text == "失败"
    assert record.stdout == "Physical density: 450"
    assert record.stderr == "error"


def test_execution_log_persists_and_reloads(tmp_path):
    path = tmp_path / "execution-log.jsonl"
    log = ExecutionLog(path)
    record = make_record()
    log.add(record)

    assert path.is_file()
    loaded = ExecutionLog(path)
    assert loaded.records() == [record]
    assert loaded.last_error == ""


def test_adb_service_records_finished_process(qtbot, tmp_path):
    log = ExecutionLog(tmp_path / "execution-log.jsonl")
    service = AdbService(Path("adb.exe"), execution_log=log)

    service.run_argv(
        [sys.executable, "-c", "print('logged-output')"],
    )
    qtbot.waitUntil(lambda: len(log.records()) == 1, timeout=5000)

    record = log.records()[0]
    assert record.ok is True
    assert record.exit_code == 0
    assert "logged-output" in record.stdout
    assert "logged-output" in Path(log.path).read_text(encoding="utf-8")


def test_adb_service_can_skip_background_poll_records(qtbot, tmp_path):
    log = ExecutionLog(tmp_path / "execution-log.jsonl")
    service = AdbService(Path("adb.exe"), execution_log=log)

    process = service.run_argv(
        [sys.executable, "-c", "print('background-poll')"],
        record=False,
    )
    spy = QSignalSpy(process.finished)
    qtbot.waitUntil(lambda: spy.count() == 1, timeout=5000)

    assert log.records() == []
    assert not Path(log.path).exists()
