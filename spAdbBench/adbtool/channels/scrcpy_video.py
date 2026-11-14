from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from PySide6.QtCore import QObject, Signal

from .scrcpy_control import bgr_to_qimage

logger = logging.getLogger(__name__)


def _default_device(serial: str):
    from wetest.scrcpy.core._device import AndroidDevice

    return AndroidDevice(
        serial=serial,
        sock_prefix="ct-scrcpy",
        launcher_config=None,
    )


def _default_stream(device, timeout: float):
    from wetest.scrcpy.core._video import VideoStreamScreenshot

    return VideoStreamScreenshot(device=device, timeout=timeout)


class ScrcpyVideoWorker(QObject):
    """Decode scrcpy frames on a background Python thread.

    ``VideoStreamScreenshot`` already keeps its own socket/decode thread; this
    wrapper feeds it without ever entering the UI thread. Signals are delivered
    to the main thread by Qt's queued connection.
    """

    frame_ready = Signal(object)
    failed = Signal(str)
    state = Signal(str)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        device_factory: Callable[[str], object] | None = None,
        stream_factory: Callable[[object], object] | None = None,
        max_fps: int = 30,
        frame_timeout: float = 2.0,
    ) -> None:
        super().__init__(parent)
        self._device_factory = device_factory or _default_device
        self._stream_factory = stream_factory or (
            lambda device: _default_stream(device, frame_timeout)
        )
        self._max_fps = max(1, min(60, int(max_fps)))
        self._frame_timeout = max(0.2, float(frame_timeout))
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._stream = None
        self._lock = threading.Lock()
        self._serial = ""

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, serial: str) -> None:
        if self.is_running:
            return
        self._serial = serial
        self._stop_event.clear()
        self.state.emit("连接中")
        self._thread = threading.Thread(
            target=self._run,
            name=f"scrcpy-video-{serial}",
            daemon=True,
        )
        self._thread.start()

    def stop(self, wait: bool = False) -> None:
        self._stop_event.set()
        if wait and self._thread is not None and self._thread.is_alive():
            if self._thread is not threading.current_thread():
                self._thread.join(timeout=1.5)

    def _run(self) -> None:
        stream = None
        error = False
        try:
            device = self._device_factory(self._serial)
            stream = self._stream_factory(device)
            with self._lock:
                self._stream = stream
            first_frame = True
            while not self._stop_event.is_set():
                started = time.perf_counter()
                try:
                    frame = stream.get_screenshot()
                except Exception as exc:
                    if self._stop_event.is_set():
                        break
                    error = True
                    self.state.emit("错误")
                    self.failed.emit(f"视频连接失败：{exc}")
                    return
                image = bgr_to_qimage(frame)
                if not image.isNull():
                    if first_frame:
                        first_frame = False
                        self.state.emit("已连接")
                    self.frame_ready.emit(image)
                elapsed = time.perf_counter() - started
                delay = max(0.0, (1.0 / self._max_fps) - elapsed)
                if self._stop_event.wait(delay):
                    break
        except Exception as exc:
            if not self._stop_event.is_set():
                error = True
                self.state.emit("错误")
                self.failed.emit(f"视频连接失败：{exc}")
        finally:
            with self._lock:
                self._stream = None
            if stream is not None:
                try:
                    stream.stop()
                except Exception:
                    logger.debug("停止 scrcpy 视频流失败", exc_info=True)
            if not error:
                self.state.emit("已停止")
