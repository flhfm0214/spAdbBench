from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QProcess

from adbtool.channels.scrcpy_window import (
    OFFSCREEN_X,
    OFFSCREEN_Y,
    READY_SETTLE_MS,
    ScrcpyWindowProcess,
)
from adbtool.services.adb import AdbService


def make_manager(tmp_path, *, create_exe: bool = True) -> ScrcpyWindowProcess:
    executable = tmp_path / "scrcpy.exe"
    if create_exe:
        executable.write_bytes(b"exe")
    return ScrcpyWindowProcess(
        AdbService(Path("adb.exe")),
        executable,
        max_fps=60,
        max_size=1080,
    )


def test_build_args_uses_serial_and_smooth_options(tmp_path):
    manager = make_manager(tmp_path)

    args = manager.build_args("ABC")

    assert args[:2] == ["--serial", "ABC"]
    assert "--no-audio" in args
    assert args[args.index("--max-fps") + 1] == "60"
    assert args[args.index("--max-size") + 1] == "1080"
    assert args[args.index("--window-title") + 1] == "手机控制 - ABC"
    assert args[args.index("--window-x") + 1] == str(OFFSCREEN_X)
    assert args[args.index("--window-y") + 1] == str(OFFSCREEN_Y)
    assert "--window-borderless" in args
    assert "--no-window-aspect-ratio-lock" in args


def test_missing_executable_emits_failed(qtbot, tmp_path):
    manager = make_manager(tmp_path, create_exe=False)

    with qtbot.waitSignal(manager.failed, timeout=2000) as blocker:
        manager.start("ABC")

    assert "scrcpy" in blocker.args[0]
    assert manager.running is False


class FakeProcess:
    def __init__(self) -> None:
        self.terminated = False
        self.waited = 0

    def state(self):
        return QProcess.ProcessState.Running

    def terminate(self) -> None:
        self.terminated = True

    def waitForFinished(self, timeout_ms: int) -> bool:
        self.waited = timeout_ms
        return True

    def deleteLater(self) -> None:
        pass


def test_stop_terminates_running_process(tmp_path):
    manager = make_manager(tmp_path)
    process = FakeProcess()
    manager._process = process

    manager.stop()

    assert process.terminated is True
    assert process.waited == 1500


def test_window_ready_waits_for_texture_and_settle(qtbot, tmp_path):
    manager = make_manager(tmp_path)
    manager._process = FakeProcess()
    manager._hwnd = 123
    seen: list[int] = []
    manager.window_ready.connect(seen.append)

    manager._schedule_ready()
    qtbot.wait(READY_SETTLE_MS + 80)
    assert seen == []
    assert manager.ready is False

    manager._texture_ready = True
    manager._schedule_ready()
    qtbot.wait(READY_SETTLE_MS + 120)

    assert seen == [123]
    assert manager.ready is True


def test_stale_process_finished_signal_is_ignored(tmp_path):
    manager = make_manager(tmp_path)
    current = FakeProcess()
    manager._process = current
    emitted: list[int] = []
    manager.finished.connect(emitted.append)

    manager._on_finished(FakeProcess(), 0, QProcess.ExitStatus.NormalExit)

    assert emitted == []
    assert manager._process is current
