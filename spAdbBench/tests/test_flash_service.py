from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal

from adbtool.services.flash import FlashService


class FakeProcess(QObject):
    finished = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.is_running = False
        self.cancelled = False

    def finish(self, ok: bool = True, stdout: str = "", stderr: str = "") -> None:
        self.is_running = False
        self.finished.emit(
            SimpleNamespace(
                ok=ok,
                stdout=stdout,
                stderr=stderr,
                cancelled=self.cancelled,
            )
        )


class FakeAdb:
    def __init__(self) -> None:
        self.adb_path = "adb.exe"
        self.runs: list[tuple[str | None, tuple[str, ...]]] = []
        self.shells: list[tuple[str, str]] = []
        self.processes: list[FakeProcess] = []

    def run(self, serial, *args, **_kwargs):
        process = FakeProcess()
        self.runs.append((serial, tuple(args)))
        self.processes.append(process)
        return process

    def shell(self, serial, script, **_kwargs):
        process = FakeProcess()
        self.shells.append((serial, script))
        self.processes.append(process)
        return process


def test_reboot_modes():
    adb = FakeAdb()
    svc = FlashService(adb)

    svc.reboot("ABC", "bootloader")
    svc.reboot("ABC", "edl")
    svc.reboot("ABC", "fastboot")

    assert adb.runs == [
        ("ABC", ("reboot", "bootloader")),
        ("ABC", ("reboot", "edl")),
        ("ABC", ("reboot", "fastboot")),
    ]
    assert svc.reboot_command("ABC", "bootloader") == "adb -s ABC reboot bootloader"


def test_fastboot_command_is_generated_not_executed():
    adb = FakeAdb()
    svc = FlashService(adb)

    command = svc.fastboot_flash_command("boot", r"C:\images\boot.img")

    assert command == 'fastboot flash boot "C:\\images\\boot.img"'
    assert adb.runs == []
    assert adb.shells == []


def test_unlock_lock_commands_use_fastboot():
    adb = FakeAdb()
    svc = FlashService(adb)

    assert svc.unlock_command("ABC") == "fastboot -s ABC oem unlock"
    assert svc.lock_command("ABC") == "fastboot -s ABC oem lock"
    assert adb.runs == []
    assert adb.shells == []


def test_repair_adb_runs_kill_then_start():
    adb = FakeAdb()
    svc = FlashService(adb)
    results = []

    job = svc.repair_adb()
    job.finished.connect(results.append)
    job.start()

    assert adb.runs == [(None, ("kill-server",))]

    adb.processes[0].finish(ok=True)
    assert adb.runs[-1] == (None, ("start-server",))
    assert len(results) == 0

    adb.processes[1].finish(ok=True, stdout="* daemon started successfully")
    assert len(results) == 1
    assert results[0].ok is True


def test_repair_adb_reports_kill_failure_without_starting():
    adb = FakeAdb()
    svc = FlashService(adb)
    results = []
    job = svc.repair_adb()
    job.finished.connect(results.append)
    job.start()

    adb.processes[0].finish(ok=False, stderr="failed")

    assert adb.runs == [(None, ("kill-server",))]
    assert len(results) == 1
    assert results[0].ok is False


def test_reconnect_and_version_commands():
    adb = FakeAdb()
    svc = FlashService(adb)

    svc.reconnect_offline()
    svc.version()

    assert adb.runs == [
        (None, ("reconnect", "offline")),
        (None, ("version",)),
    ]


def test_reboot_rejects_unknown_mode_and_invalid_serial():
    svc = FlashService(FakeAdb())

    with pytest.raises(ValueError):
        svc.reboot("ABC", "download")
    with pytest.raises(ValueError):
        svc.reboot("bad serial", "bootloader")


def test_fastboot_command_rejects_bad_partition_or_path():
    svc = FlashService(FakeAdb())

    with pytest.raises(ValueError):
        svc.fastboot_flash_command("boot; rm", r"C:\images\boot.img")
    with pytest.raises(ValueError):
        svc.fastboot_flash_command("boot", "")
    with pytest.raises(ValueError):
        svc.fastboot_flash_command("boot", 'C:\\images\\bad"name.img')
