from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

import numpy as np
from PySide6.QtCore import (
    QCoreApplication,
    QObject,
    QPoint,
    QRect,
    QSize,
    QThread,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QImage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ControlInfo:
    width: int
    height: int


def map_click(
    pos: QPoint,
    widget_size: QSize,
    image_size: QRect,
) -> tuple[float, float] | None:
    """Map a widget point onto the fitted image and return normalized coordinates.

    The image is letterboxed/pillarboxed inside the widget. Points in the black
    bars return ``None``; the session only receives coordinates in ``0..1``.
    """
    image_width = image_size.width()
    image_height = image_size.height()
    widget_width = widget_size.width()
    widget_height = widget_size.height()
    if image_width <= 0 or image_height <= 0 or widget_width <= 0 or widget_height <= 0:
        return None

    scale = min(widget_width / image_width, widget_height / image_height)
    draw_width = image_width * scale
    draw_height = image_height * scale
    offset_x = (widget_width - draw_width) / 2
    offset_y = (widget_height - draw_height) / 2

    x = float(pos.x())
    y = float(pos.y())
    if x < offset_x or x > offset_x + draw_width:
        return None
    if y < offset_y or y > offset_y + draw_height:
        return None
    return ((x - offset_x) / draw_width, (y - offset_y) / draw_height)


def bgr_to_qimage(frame: np.ndarray | None) -> QImage:
    """Copy a BGR numpy frame into a QImage that owns its pixels."""
    if frame is None:
        return QImage()
    array = np.asarray(frame)
    if array.ndim != 3 or array.shape[0] <= 0 or array.shape[1] <= 0:
        return QImage()
    array = np.ascontiguousarray(array)
    height, width, channels = array.shape
    if channels == 3:
        fmt = QImage.Format.Format_BGR888
    elif channels == 4:
        fmt = QImage.Format.Format_ARGB32
    elif channels == 1:
        fmt = QImage.Format.Format_Grayscale8
    else:
        return QImage()
    return QImage(
        array.data,
        width,
        height,
        int(array.strides[0]),
        fmt,
    ).copy()


def _default_device(serial: str):
    from wetest.scrcpy.core._device import AndroidDevice

    return AndroidDevice(
        serial=serial,
        sock_prefix="ct-scrcpy",
        launcher_config=None,
    )


def _default_connection(device):
    from wetest.scrcpy.core._control import CtrlConnection

    return CtrlConnection(device=device, timeout=2.0)


class ScrcpyControlWorker(QObject):
    """Runs scrcpy control operations outside the UI thread.

    The worker is moved to a QThread by ``ScrcpySession``. Methods invoked from
    the UI are queued; the connection retry timer also lives in that thread.
    """

    connected = Signal(object)
    failed = Signal(str)
    screenshot_ready = Signal(object)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        device_factory: Callable[[str], object] | None = None,
        connection_factory: Callable[[object], object] | None = None,
        max_size: int = 1080,
        screenshot_quality: int = 80,
        retry_ms: int = 500,
        max_attempts: int = 40,
    ) -> None:
        super().__init__(parent)
        self._device_factory = device_factory or _default_device
        self._connection_factory = connection_factory or _default_connection
        self._max_size = max_size
        self._quality = screenshot_quality
        self._retry_ms = max(1, int(retry_ms))
        self._max_attempts = max(1, int(max_attempts))
        self._serial = ""
        self._device = None
        self._connection = None
        self._info: ControlInfo | None = None
        self._attempts = 0
        self._want_connection = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._attempt_connect)

    @property
    def info(self) -> ControlInfo | None:
        return self._info

    @Slot(str)
    def connect_device(self, serial: str) -> None:
        self.disconnect()
        self._serial = serial
        self._want_connection = True
        self._attempts = 0
        self._timer.start(0)

    def _attempt_connect(self) -> None:
        if not self._want_connection:
            return
        connection = None
        try:
            if self._device is None:
                self._device = self._device_factory(self._serial)
            connection = self._connection_factory(self._device)
            screen = connection.screen_info
            info = ControlInfo(width=int(screen.Width), height=int(screen.Height))
            self._connection = connection
            self._info = info
            self._want_connection = False
            self.connected.emit(info)
        except Exception as exc:
            if connection is not None:
                self._close_object(connection)
            self._attempts += 1
            if self._attempts >= self._max_attempts:
                self._want_connection = False
                self.failed.emit(f"控制连接失败：{exc}")
            else:
                self._timer.start(self._retry_ms)

    def _require_connection(self) -> bool:
        if self._connection is None or self._info is None:
            self.failed.emit("控制通道未连接")
            return False
        return True

    @Slot(float, float)
    def tap(self, nx: float, ny: float) -> None:
        if not self._require_connection():
            return
        try:
            from wetest.scrcpy.const import Action

            x, y = self._clamp(nx), self._clamp(ny)
            self._connection.touch(x, y, Action.DOWN)
            self._connection.touch(x, y, Action.UP)
        except Exception as exc:
            self.failed.emit(f"点击失败：{exc}")

    @Slot(float, float, float, float, int)
    def swipe(
        self,
        nx: float,
        ny: float,
        ex: float,
        ey: float,
        duration_ms: int = 300,
    ) -> None:
        if not self._require_connection():
            return
        try:
            width = self._info.width
            height = self._info.height
            sx, sy = self._clamp(nx) * width, self._clamp(ny) * height
            tx, ty = self._clamp(ex) * width, self._clamp(ey) * height
            distance = max(abs(tx - sx), abs(ty - sy))
            steps = max(1, int(distance / 5))
            delay = max(0.001, (max(0, duration_ms) / 1000) / steps)
            self._connection.swipe(
                sx,
                sy,
                tx,
                ty,
                move_step_length=5,
                move_steps_delay=delay,
            )
        except Exception as exc:
            self.failed.emit(f"滑动失败：{exc}")

    @Slot(int)
    def press(self, keycode: int) -> None:
        if not self._require_connection():
            return
        try:
            self._connection.press_button(keycode)
        except Exception as exc:
            self.failed.emit(f"按键失败：{exc}")

    @Slot()
    def screenshot(self) -> None:
        if not self._require_connection():
            return
        try:
            frame = self._connection.screenshot(self._max_size, self._quality)
            image = bgr_to_qimage(frame)
            if image.isNull():
                self.failed.emit("截图失败：返回了空画面")
                return
            self.screenshot_ready.emit(image)
        except Exception as exc:
            self.failed.emit(f"截图失败：{exc}")

    @Slot()
    def disconnect(self) -> None:
        self._want_connection = False
        self._timer.stop()
        self._close_connection()
        self._device = None
        self._info = None

    @Slot()
    def shutdown(self) -> None:
        self.disconnect()
        app = QCoreApplication.instance()
        if app is not None and QThread.currentThread() is not app.thread():
            QThread.currentThread().quit()

    def _close_connection(self) -> None:
        if self._connection is not None:
            self._close_object(self._connection)
            self._connection = None

    @staticmethod
    def _close_object(obj) -> None:
        close = getattr(obj, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                logger.debug("关闭 scrcpy 控制连接失败", exc_info=True)

    @staticmethod
    def _clamp(value: float) -> float:
        return min(1.0, max(0.0, float(value)))
