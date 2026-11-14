from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Q_ARG, QMetaObject, QObject, QThread, Qt, Signal

from ..infrastructure.config import AppConfig
from ..infrastructure.resource_paths import resolve_resource
from .scrcpy_control import ControlInfo, ScrcpyControlWorker
from .scrcpy_server import ScrcpyServerProcess
from .scrcpy_video import ScrcpyVideoWorker


class ScrcpySession(QObject):
    """Coordinates server, control and video channels for one device."""

    frame_ready = Signal(object)
    # Frames are tagged with the session that produced them so a preview can
    # ignore late frames from the device that was just switched away from.
    frame_for_serial = Signal(str, object)
    state_changed = Signal(str)
    error = Signal(str)
    control_ready = Signal(object)
    screenshot_ready = Signal(object)
    log_message = Signal(str)

    def __init__(
        self,
        config: AppConfig,
        adb,
        parent: QObject | None = None,
        *,
        max_fps: int | None = None,
        server_factory: Callable | None = None,
        control_factory: Callable | None = None,
        video_factory: Callable | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.adb = adb
        self.max_fps = max(
            1,
            int(max_fps if max_fps is not None else config.scrcpy_max_fps),
        )
        self._server_factory = server_factory or self._make_server
        self._control_factory = control_factory or self._make_control
        self._video_factory = video_factory or self._make_video
        self._state = "空闲"
        self._serial = ""
        self._generation = 0
        self._stopping = False
        self._failed = False
        self._control_ready = False
        self._info: ControlInfo | None = None
        self._last_frame = None
        self.server: ScrcpyServerProcess | None = None
        self.control: ScrcpyControlWorker | None = None
        self.video: ScrcpyVideoWorker | None = None
        self.control_thread: QThread | None = None

    @property
    def state(self) -> str:
        return self._state

    @property
    def serial(self) -> str:
        return self._serial

    @property
    def control_info(self) -> ControlInfo | None:
        return self._info

    def _make_server(self, adb, path: Path, config: AppConfig):
        return ScrcpyServerProcess(
            adb,
            path,
            self,
            max_size=config.scrcpy_max_size,
            max_fps=self.max_fps,
        )

    def _make_control(self):
        return ScrcpyControlWorker(
            max_size=self.config.scrcpy_max_size,
        )

    def _make_video(self, max_fps: int):
        return ScrcpyVideoWorker(max_fps=max_fps)

    def start(self, serial: str) -> None:
        if not serial:
            self._fail("未选择设备，无法启动 scrcpy")
            return
        self._teardown()
        generation = self._generation
        self._serial = serial
        self._stopping = False
        self._failed = False
        self._control_ready = False
        self._info = None
        self._last_frame = None
        self._set_state("启动服务")
        try:
            server_path = resolve_resource(
                self.config.scrcpy_server_path,
                "vendor/scrcpy/scrcpy-server",
            )
            self.server = self._server_factory(
                self.adb,
                server_path,
                self.config,
            )
            self.server.ready.connect(
                lambda g=generation: self._on_server_ready(g)
            )
            self.server.failed.connect(
                lambda message, g=generation: self._fail(message, g)
            )
            self.server.log.connect(self.log_message)
            self.server.start(serial)
        except Exception as exc:
            self._fail(f"启动 scrcpy-server 失败：{exc}", generation)

    def stop(self) -> None:
        if self._state in {"空闲", "已停止"} and self.server is None:
            return
        self._teardown()
        self._set_state("已停止")

    shutdown = stop

    def _on_server_ready(self, generation: int) -> None:
        if not self._is_current(generation):
            return
        self._set_state("等待控制连接")
        try:
            self.control = self._control_factory()
            self.control.connected.connect(
                lambda info, g=generation: self._on_control_connected(info, g)
            )
            self.control.failed.connect(
                lambda message, g=generation: self._fail(message, g)
            )
            self.control.screenshot_ready.connect(self.screenshot_ready.emit)
            thread = QThread(self)
            self.control_thread = thread
            self.control.moveToThread(thread)
            thread.start()
            self._invoke_control("connect_device", self._serial)
        except Exception as exc:
            self._fail(f"启动控制通道失败：{exc}", generation)

    def _on_control_connected(self, info: ControlInfo, generation: int) -> None:
        if not self._is_current(generation):
            return
        self._control_ready = True
        self._info = info
        self.control_ready.emit(info)
        self._set_state("等待视频")
        try:
            self.video = self._video_factory(self.max_fps)
            self.video.frame_ready.connect(
                lambda image, g=generation: self._on_frame(image, g)
            )
            self.video.failed.connect(
                lambda message, g=generation: self._fail(message, g)
            )
            self.video.state.connect(
                lambda state, g=generation: self._on_video_state(state, g)
            )
            self.video.start(self._serial)
        except Exception as exc:
            self._fail(f"启动视频通道失败：{exc}", generation)

    def _on_video_state(self, state: str, generation: int) -> None:
        if not self._is_current(generation) or self._failed:
            return
        if state == "已连接":
            self._set_state("已连接")

    def _on_frame(self, image, generation: int) -> None:
        if not self._is_current(generation):
            return
        if not image.isNull():
            self._last_frame = image.copy()
        if self._state != "已连接":
            self._set_state("已连接")
        self.frame_for_serial.emit(self._serial, image)
        self.frame_ready.emit(image)

    def _require_control(self) -> bool:
        if not self._control_ready or self.control is None:
            self.error.emit("控制通道未连接")
            return False
        return True

    def tap_norm(self, nx: float, ny: float) -> None:
        if self._require_control():
            self._invoke_control("tap", float(nx), float(ny))

    def swipe_norm(
        self,
        nx: float,
        ny: float,
        ex: float,
        ey: float,
        duration_ms: int = 300,
    ) -> None:
        if self._require_control():
            self._invoke_control(
                "swipe",
                float(nx),
                float(ny),
                float(ex),
                float(ey),
                int(duration_ms),
            )

    def press(self, keycode: int) -> None:
        if self._require_control():
            self._invoke_control("press", int(keycode))

    def screenshot(self) -> None:
        if self._last_frame is not None and not self._last_frame.isNull():
            # The Tencent server reports an empty CAPTURE response on some
            # devices; reuse the latest decoded video frame instead.
            self.screenshot_ready.emit(self._last_frame.copy())
            return
        if self._require_control():
            self._invoke_control("screenshot")

    def _invoke_control(self, method: str, *args) -> None:
        control = self.control
        if control is None:
            return
        qt_args = []
        for value in args:
            if isinstance(value, bool):
                qt_args.append(Q_ARG(bool, value))
            elif isinstance(value, int):
                qt_args.append(Q_ARG(int, value))
            elif isinstance(value, float):
                qt_args.append(Q_ARG(float, value))
            else:
                qt_args.append(Q_ARG(str, str(value)))
        QMetaObject.invokeMethod(
            control,
            method,
            Qt.ConnectionType.QueuedConnection,
            *qt_args,
        )

    def _fail(self, message: str, generation: int | None = None) -> None:
        if generation is not None and not self._is_current(generation):
            return
        if self._stopping or self._failed:
            return
        self._failed = True
        self._set_state("错误")
        self.error.emit(message)
        self._teardown()

    def _is_current(self, generation: int) -> bool:
        return (
            generation == self._generation
            and not self._stopping
            and not self._failed
        )

    def _teardown(self) -> None:
        self._generation += 1
        self._stopping = True
        self._control_ready = False
        self._last_frame = None

        video, self.video = self.video, None
        if video is not None:
            try:
                video.stop()
            except Exception:
                pass

        control, self.control = self.control, None
        thread, self.control_thread = self.control_thread, None
        if control is not None:
            try:
                self._invoke_worker(control, "shutdown")
            except Exception:
                pass
            if thread is not None and thread.isRunning():
                if not thread.wait(1500):
                    thread.quit()
                    thread.wait(300)

        server = self.server
        if server is not None:
            try:
                server.stop()
            except Exception:
                pass

    @staticmethod
    def _invoke_worker(worker, method: str) -> None:
        QMetaObject.invokeMethod(
            worker,
            method,
            Qt.ConnectionType.QueuedConnection,
        )

    def _set_state(self, state: str) -> None:
        if state == self._state:
            return
        self._state = state
        self.state_changed.emit(state)
