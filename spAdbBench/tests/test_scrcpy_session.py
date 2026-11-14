from __future__ import annotations

import sys
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PySide6.QtCore import QObject, QProcess, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QImage

from adbtool.channels.scrcpy_control import ControlInfo, ScrcpyControlWorker
from adbtool.channels.scrcpy_server import ScrcpyServerProcess
from adbtool.channels.scrcpy_session import ScrcpySession
from adbtool.channels.scrcpy_video import ScrcpyVideoWorker
from adbtool.infrastructure.config import AppConfig
from adbtool.services.adb import AdbService


class FakePush:
    def __init__(self) -> None:
        self.finished = _Signal()
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class _Signal:
    def __init__(self) -> None:
        self._callbacks = []

    def connect(self, callback) -> None:
        self._callbacks.append(callback)


class FakeAdb:
    def __init__(self) -> None:
        self.calls: list[tuple[str | None, tuple[str, ...]]] = []
        self.process = FakePush()

    def build(self, serial: str | None, *args: str) -> list[str]:
        prefix = ["adb.exe"]
        if serial:
            prefix.extend(["-s", serial])
        prefix.extend(args)
        return prefix

    def run(self, serial: str | None, *args: str, **_kwargs):
        self.calls.append((serial, args))
        return self.process


class FakeServer(QObject):
    ready = Signal()
    log = Signal(str)
    failed = Signal(str)
    state = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.process = QProcess()
        self.started_serial = ""
        self.stopped = False

    def start(self, serial: str) -> None:
        self.started_serial = serial
        self.state.emit("运行中")
        QTimer.singleShot(0, self.ready.emit)

    def stop(self) -> None:
        self.stopped = True
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
            self.process.waitForFinished(500)


class FakeControl(QObject):
    connected = Signal(object)
    failed = Signal(str)
    screenshot_ready = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.serial = ""
        self.taps: list[tuple[float, float]] = []
        self.swipes: list[tuple[float, float, float, float, int]] = []
        self.presses: list[int] = []
        self.screenshots = 0
        self.shutdown_called = False

    @Slot(str)
    def connect_device(self, serial: str) -> None:
        self.serial = serial
        self.connected.emit(ControlInfo(width=1000, height=500))

    @Slot(float, float)
    def tap(self, nx: float, ny: float) -> None:
        self.taps.append((nx, ny))

    @Slot(float, float, float, float, int)
    def swipe(self, nx: float, ny: float, ex: float, ey: float, duration_ms: int) -> None:
        self.swipes.append((nx, ny, ex, ey, duration_ms))

    @Slot(int)
    def press(self, keycode: int) -> None:
        self.presses.append(keycode)

    @Slot()
    def screenshot(self) -> None:
        self.screenshots += 1

    @Slot()
    def shutdown(self) -> None:
        self.shutdown_called = True
        QThread.currentThread().quit()


class FakeVideo(QObject):
    frame_ready = Signal(object)
    failed = Signal(str)
    state = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.serial = ""
        self.started = False
        self.stopped = False

    def start(self, serial: str) -> None:
        self.serial = serial
        self.started = True
        QTimer.singleShot(0, lambda: self.state.emit("已连接"))

    def stop(self) -> None:
        self.stopped = True


def test_session_reports_error_when_server_missing(qtbot, tmp_path):
    config = AppConfig(scrcpy_server_path=str(tmp_path / "missing"))
    session = ScrcpySession(config, AdbService(Path("adb.exe")))

    with qtbot.waitSignal(session.error, timeout=3000) as blocker:
        session.start("ABC")

    assert "scrcpy-server" in blocker.args[0]
    assert session.state == "错误"


def test_session_orchestrates_and_routes_control(qtbot, tmp_path):
    config = AppConfig(scrcpy_server_path=str(tmp_path / "scrcpy-server"))
    Path(config.scrcpy_server_path).write_bytes(b"server")
    server = FakeServer()
    control = FakeControl()
    video = FakeVideo()
    session = ScrcpySession(
        config,
        AdbService(Path("adb.exe")),
        server_factory=lambda *_args: server,
        control_factory=lambda: control,
        video_factory=lambda _max_fps: video,
    )

    with qtbot.waitSignal(session.control_ready, timeout=3000):
        session.start("ABC")
    qtbot.waitUntil(lambda: session.state == "已连接", timeout=3000)

    assert server.started_serial == "ABC"
    assert control.serial == "ABC"
    assert video.started is True
    assert video.serial == "ABC"

    session.tap_norm(0.25, 0.75)
    session.swipe_norm(0.1, 0.2, 0.8, 0.9, 400)
    session.press(3)
    frame = QImage(4, 2, QImage.Format.Format_RGB32)
    frame.fill(0xFF336699)
    with qtbot.waitSignal(session.frame_ready, timeout=2000):
        video.frame_ready.emit(frame)
    with qtbot.waitSignal(session.screenshot_ready, timeout=2000) as shot:
        session.screenshot()
    qtbot.waitUntil(lambda: control.taps == [(0.25, 0.75)], timeout=2000)
    qtbot.waitUntil(lambda: control.swipes == [(0.1, 0.2, 0.8, 0.9, 400)], timeout=2000)
    qtbot.waitUntil(lambda: control.presses == [3], timeout=2000)
    assert (shot.args[0].width(), shot.args[0].height()) == (4, 2)
    assert control.screenshots == 0

    session.stop()

    assert session.state == "已停止"
    assert session.server is server
    assert server.stopped is True
    assert video.stopped is True
    assert control.shutdown_called is True
    assert server.process.state() == QProcess.ProcessState.NotRunning

    video.frame_ready.emit(frame)
    qtbot.wait(20)
    assert session.state == "已停止"


def test_server_command_uses_wetest_protocol(tmp_path):
    server_path = tmp_path / "scrcpy-server"
    server_path.write_bytes(b"server")
    server = ScrcpyServerProcess(
        AdbService(Path("adb.exe")),
        server_path,
        max_size=720,
        max_fps=24,
        bit_rate=4_000_000,
    )

    argv = server.build_server_argv("ABC")

    assert argv[:4] == ["adb.exe", "-s", "ABC", "shell"]
    command = argv[4]
    assert "CLASSPATH=/data/local/tmp/adbtool-scrcpy-server.jar" in command
    assert "com.genymobile.scrcpy.Server 1.2.4" in command
    assert "max_size=720" in command
    assert "max_fps=24" in command
    assert "bit_rate=4000000" in command
    assert "tunnel_forward=true" in command
    assert "udt_socket_name=ct-scrcpy" in command
    assert "clipboard_autosync=false" in command


def test_server_missing_file_emits_failed(qtbot, tmp_path):
    server = ScrcpyServerProcess(AdbService(Path("adb.exe")), tmp_path / "missing")

    with qtbot.waitSignal(server.failed, timeout=2000) as blocker:
        server.start("ABC")

    assert "scrcpy-server" in blocker.args[0]


def test_server_pushes_then_stop_cancels_push(tmp_path):
    server_path = tmp_path / "scrcpy-server"
    server_path.write_bytes(b"server")
    adb = FakeAdb()
    server = ScrcpyServerProcess(adb, server_path)

    server.start("ABC")

    assert adb.calls == [
        (
            "ABC",
            ("push", str(server_path), "/data/local/tmp/adbtool-scrcpy-server.jar"),
        )
    ]
    server.stop()
    assert adb.process.cancelled is True


def test_server_stop_kills_running_process(tmp_path):
    server_path = tmp_path / "scrcpy-server"
    server_path.write_bytes(b"server")
    server = ScrcpyServerProcess(AdbService(Path("adb.exe")), server_path)
    process = server.process
    process.start(sys.executable, ["-c", "import time; time.sleep(30)"])
    assert process.waitForStarted(2000)

    server.stop()

    assert process.state() == QProcess.ProcessState.NotRunning


class FakeCtrlConnection:
    def __init__(self) -> None:
        self.screen_info = SimpleNamespace(Width=1000, Height=500)
        self.touches: list[tuple[float, float, int]] = []
        self.swipes: list[tuple[float, float, float, float]] = []
        self.screenshots = 0

    def touch(self, x: float, y: float, action: int) -> None:
        self.touches.append((x, y, int(action)))

    def swipe(self, sx: float, sy: float, ex: float, ey: float, **_kwargs) -> None:
        self.swipes.append((sx, sy, ex, ey))

    def screenshot(self, _max_size: int, _quality: int) -> np.ndarray:
        self.screenshots += 1
        return np.zeros((2, 3, 3), dtype=np.uint8)

    def close(self) -> None:
        pass


def test_control_worker_taps_with_normalized_coordinates(qtbot):
    connection = FakeCtrlConnection()
    worker = ScrcpyControlWorker(
        device_factory=lambda _serial: object(),
        connection_factory=lambda _device: connection,
        retry_ms=10,
        max_attempts=2,
    )

    with qtbot.waitSignal(worker.connected, timeout=2000) as blocker:
        worker.connect_device("ABC")

    info = blocker.args[0]
    assert (info.width, info.height) == (1000, 500)

    worker.tap(0.25, 0.75)
    worker.swipe(0.1, 0.2, 0.8, 0.9, 400)

    assert connection.touches == [(0.25, 0.75, 0), (0.25, 0.75, 1)]
    assert connection.swipes[0][:2] == (100.0, 100.0)
    assert connection.swipes[0][2:] == (800.0, 450.0)


def test_control_worker_converts_screenshot_to_qimage(qtbot):
    connection = FakeCtrlConnection()
    worker = ScrcpyControlWorker(
        device_factory=lambda _serial: object(),
        connection_factory=lambda _device: connection,
        retry_ms=10,
        max_attempts=2,
    )
    with qtbot.waitSignal(worker.connected, timeout=2000):
        worker.connect_device("ABC")

    with qtbot.waitSignal(worker.screenshot_ready, timeout=2000) as blocker:
        worker.screenshot()

    image = blocker.args[0]
    assert not image.isNull()
    assert (image.width(), image.height()) == (3, 2)


class FakeVideoStream:
    def __init__(self) -> None:
        self.stopped = False

    def get_screenshot(self) -> np.ndarray:
        time.sleep(0.01)
        return np.zeros((2, 3, 3), dtype=np.uint8)

    def stop(self) -> None:
        self.stopped = True


def test_video_worker_emits_frames(qtbot):
    stream = FakeVideoStream()
    worker = ScrcpyVideoWorker(
        device_factory=lambda _serial: object(),
        stream_factory=lambda _device: stream,
        max_fps=60,
        frame_timeout=1.0,
    )

    with qtbot.waitSignal(worker.frame_ready, timeout=2000) as blocker:
        worker.start("ABC")

    image = blocker.args[0]
    assert (image.width(), image.height()) == (3, 2)
    worker.stop()


def test_video_worker_reports_failure(qtbot):
    class BrokenStream:
        def get_screenshot(self):
            raise RuntimeError("no video")

        def stop(self):
            pass

    worker = ScrcpyVideoWorker(
        device_factory=lambda _serial: object(),
        stream_factory=lambda _device: BrokenStream(),
        max_fps=30,
        frame_timeout=1.0,
    )

    with qtbot.waitSignal(worker.failed, timeout=2000) as blocker:
        worker.start("ABC")

    assert "no video" in blocker.args[0]
    worker.stop()
