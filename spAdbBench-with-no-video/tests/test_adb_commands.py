from pathlib import Path

from adbtool.services.adb import AdbService


def test_build_with_serial():
    service = AdbService(Path("adb.exe"))

    assert service.build("ABC", "shell", "pm", "list", "packages") == [
        "adb.exe",
        "-s",
        "ABC",
        "shell",
        "pm",
        "list",
        "packages",
    ]


def test_build_without_serial():
    service = AdbService(Path("adb.exe"))

    assert service.build(None, "devices", "-l") == ["adb.exe", "devices", "-l"]


def test_shell_argv_keeps_script_as_one_argument():
    service = AdbService(Path("adb.exe"))

    assert service.shell_argv("ABC", "ls '/sdcard/a b'") == [
        "adb.exe",
        "-s",
        "ABC",
        "shell",
        "ls '/sdcard/a b'",
    ]


def test_shutdown_cancels_and_waits_for_active_processes():
    service = AdbService(Path("adb.exe"))

    class FakeProcess:
        def __init__(self) -> None:
            self.cancelled = False
            self.waited = 0

        def cancel(self) -> None:
            self.cancelled = True

        def wait(self, timeout_ms: int) -> None:
            self.waited = timeout_ms

    process = FakeProcess()
    service._active.add(process)

    service.shutdown()

    assert process.cancelled is True
    assert process.waited == 1000
    assert not service._active
