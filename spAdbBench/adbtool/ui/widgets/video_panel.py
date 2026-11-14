from __future__ import annotations

import time

from PySide6.QtCore import QPoint, QRect, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QImage, QPixmap, QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...channels.scrcpy_control import map_click

_ACTIVE_STATES = {"启动服务", "等待控制连接", "等待视频", "已连接"}
_DRAG_THRESHOLD_SQUARED = 36


class _VideoLabel(QLabel):
    pressed = Signal(object)
    moved = Signal(object)
    released = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)

    def sizeHint(self) -> QSize:
        return QSize(320, 240)

    def minimumSizeHint(self) -> QSize:
        return QSize(0, 0)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.pressed.emit(event.position().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        self.moved.emit(event.position().toPoint())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.released.emit(event.position().toPoint())
            event.accept()
            return
        super().mouseReleaseEvent(event)


class VideoPanel(QWidget):
    tap = Signal(float, float)
    swipe = Signal(float, float, float, float, int)
    reconnect = Signal()
    disconnect_requested = Signal()
    open_window = Signal()
    toggle_preview = Signal()

    def __init__(
        self,
        session=None,
        parent: QWidget | None = None,
        *,
        preview_only: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ScreenPreview" if preview_only else "VideoPanel")
        self._session = session
        self.preview_only = preview_only
        self._interactive = not preview_only
        self._image = QImage()
        self._serial = ""
        self._state = "未连接"
        self._preview_enabled = True
        self._press_pos: QPoint | None = None
        self._press_norm: tuple[float, float] | None = None
        self._press_time = 0.0
        self._dragging = False

        self.device_label = QLabel("未连接设备")
        self.device_label.setObjectName("VideoDevice")
        self.device_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        self.state_label = QLabel("未连接")
        self.state_label.setObjectName("VideoStatus")

        self.reconnect_button = QPushButton("重连")
        self.reconnect_button.setEnabled(False)
        self.disconnect_button = QPushButton("断开")
        self.disconnect_button.setEnabled(False)
        self.open_window_button = QPushButton(
            "打开独立窗口操作设备" if preview_only else "独立窗口"
        )
        self.open_window_button.setEnabled(False)
        self.preview_toggle_button = QPushButton("关闭预览")
        self.preview_toggle_button.setToolTip("关闭预览可减少设备性能消耗")
        if preview_only:
            self.open_window_button.setObjectName("Primary")
            self.open_window_button.setMinimumHeight(42)
            self.open_window_button.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )
            self.preview_toggle_button.setMinimumHeight(42)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        top.addWidget(self.device_label, 1)
        top.addWidget(self.state_label)
        top.addWidget(self.reconnect_button)
        top.addWidget(self.disconnect_button)

        self.image_label = _VideoLabel()
        self.image_label.setObjectName("VideoCanvas")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(0, 0)
        self.image_label.setText("暂无画面")
        self.image_label.setCursor(
            Qt.CursorShape.PointingHandCursor
            if self._interactive
            else Qt.CursorShape.ArrowCursor
        )
        self.image_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        hint = QLabel("点击 / 拖动控制设备" if not preview_only else "")
        hint.setObjectName("Muted")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if preview_only:
            hint.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        if not preview_only:
            layout.addLayout(top)
        layout.addWidget(self.image_label, 1)

        if preview_only:
            bottom = QHBoxLayout()
            bottom.setContentsMargins(0, 0, 0, 0)
            bottom.setSpacing(6)
            bottom.addWidget(self.preview_toggle_button)
            bottom.addWidget(self.open_window_button, 1)
        else:
            bottom = QHBoxLayout()
            bottom.setContentsMargins(0, 0, 0, 0)
            bottom.setSpacing(6)
            bottom.addWidget(hint, 1)
            bottom.addWidget(self.open_window_button)
        layout.addLayout(bottom)

        self.image_label.pressed.connect(self._on_pressed)
        self.image_label.moved.connect(self._on_moved)
        self.image_label.released.connect(self._on_released)
        self.reconnect_button.clicked.connect(self.reconnect.emit)
        self.disconnect_button.clicked.connect(self.disconnect_requested.emit)
        self.open_window_button.clicked.connect(self.open_window.emit)
        self.preview_toggle_button.clicked.connect(self.toggle_preview.emit)

        if session is not None:
            self.tap.connect(session.tap_norm)
            self.swipe.connect(session.swipe_norm)

    @property
    def device_serial(self) -> str:
        return self._serial

    @property
    def state(self) -> str:
        return self._state

    @property
    def preview_enabled(self) -> bool:
        return self._preview_enabled

    def set_preview_enabled(self, enabled: bool) -> None:
        self._preview_enabled = bool(enabled)
        self.preview_toggle_button.setText(
            "关闭预览" if self._preview_enabled else "启用预览"
        )
        if not self._preview_enabled:
            self._image = QImage()
            self.image_label.clear()
            self.image_label.setText("预览已关闭")
            self.set_state("已停止")
        elif self._image.isNull():
            self.image_label.setText("暂无画面")
            self.set_state("待连接" if self._serial else "未连接")
        else:
            self._render_frame()

    def set_device(self, serial: str | None) -> None:
        new_serial = serial or ""
        if new_serial != self._serial:
            self._image = QImage()
            self.image_label.clear()
            self.image_label.setText(
                "暂无画面" if self._preview_enabled else "预览已关闭"
            )
        self._serial = new_serial
        self.device_label.setText(
            f"设备 {self._serial}" if self._serial else "未连接设备"
        )
        self.device_label.setToolTip(self._serial)
        self.open_window_button.setEnabled(bool(self._serial))
        if not self._preview_enabled:
            self.set_state("已停止")
        elif self._serial:
            self.set_state("待连接")
        else:
            self.set_state("未连接")

    def set_state(self, state: str) -> None:
        self._state = state or "未连接"
        if not self._preview_enabled:
            self.state_label.setText("预览已关闭")
        else:
            self.state_label.setText(self._display_state(self._state))
        self.state_label.setToolTip(self._state)
        active = self._state in _ACTIVE_STATES
        self.reconnect_button.setEnabled(bool(self._serial) and not active)
        self.disconnect_button.setEnabled(active)

    def set_frame(self, image: QImage) -> None:
        if not self._preview_enabled:
            return
        if image is None or image.isNull():
            return
        self._image = image.copy()
        self.image_label.setText("")
        self._render_frame()

    def set_frame_for(self, serial: str, image: QImage) -> None:
        """Accept a frame only when it belongs to the selected device."""
        if not serial or serial != self._serial:
            return
        self.set_frame(image)

    def refresh(self) -> None:
        self._render_frame()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._render_frame()
        QTimer.singleShot(0, self._render_frame)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._render_frame)

    def _render_frame(self) -> None:
        if self._image.isNull():
            return
        target = self.image_label.size()
        if target.width() <= 0 or target.height() <= 0:
            return
        scaled = self._image.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(QPixmap.fromImage(scaled))

    def _map(self, pos: QPoint) -> tuple[float, float] | None:
        if self._image.isNull():
            return None
        return map_click(
            pos,
            self.image_label.size(),
            QRect(0, 0, self._image.width(), self._image.height()),
        )

    def _on_pressed(self, pos: QPoint) -> None:
        if not self._interactive:
            return
        normalized = self._map(pos)
        if normalized is None:
            self._press_pos = None
            self._press_norm = None
            return
        self._press_pos = QPoint(pos)
        self._press_norm = normalized
        self._press_time = time.perf_counter()
        self._dragging = False

    def _on_moved(self, pos: QPoint) -> None:
        if self._press_pos is None:
            return
        delta = pos - self._press_pos
        if delta.x() * delta.x() + delta.y() * delta.y() > _DRAG_THRESHOLD_SQUARED:
            self._dragging = True

    def _on_released(self, pos: QPoint) -> None:
        if self._press_pos is None or self._press_norm is None:
            self._reset_press()
            return
        end = self._map(pos)
        if end is None:
            self._reset_press()
            return
        delta = pos - self._press_pos
        if delta.x() * delta.x() + delta.y() * delta.y() > _DRAG_THRESHOLD_SQUARED:
            self._dragging = True
        start = self._press_norm
        duration_ms = max(50, int((time.perf_counter() - self._press_time) * 1000))
        if self._dragging:
            self.swipe.emit(start[0], start[1], end[0], end[1], duration_ms)
        else:
            self.tap.emit(end[0], end[1])
        self._reset_press()

    def _reset_press(self) -> None:
        self._press_pos = None
        self._press_norm = None
        self._dragging = False

    @staticmethod
    def _display_state(state: str) -> str:
        if state == "空闲":
            return "未连接"
        if state == "已停止":
            return "已断开"
        if state.startswith("错误"):
            return "错误"
        return state
