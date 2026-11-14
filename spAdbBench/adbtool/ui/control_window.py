from __future__ import annotations

import ctypes
import ctypes.wintypes
import sys

from PySide6.QtCore import QEvent, QObject, QPoint, QTimer, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QBoxLayout,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..channels.scrcpy_window import ScrcpyWindowProcess
from ..infrastructure.paths import vendor_scrcpy_exe
from ..services.metrics import parse_rotation
from .widgets.control_telemetry import ControlTelemetry

KEY_BUTTONS = [
    ("主页", 3),
    ("返回", 4),
    ("任务", 187),
    ("音量 +", 24),
    ("音量 -", 25),
    ("电源", 26),
    ("菜单", 82),
]

# One light display dump is enough to detect rotation; avoid dumping the whole
# input service (dumpsys input) every second.
_ROTATION_SCRIPT = (
    'dumpsys display 2>/dev/null | grep -m1 -E "mCurrentOrientation=|mRotation="'
)


class _OrientationWatcher(QObject):
    rotation_changed = Signal(int)

    def __init__(self, adb, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.adb = adb
        self.serial = ""
        self._process = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._poll)

    def set_serial(self, serial: str) -> None:
        self.stop()
        self.serial = serial
        if serial:
            QTimer.singleShot(0, self._poll)

    def _poll(self) -> None:
        if not self.serial or self._process is not None:
            return
        process = self.adb.shell(
            self.serial,
            _ROTATION_SCRIPT,
            timeout_ms=6000,
            record=False,
        )
        self._process = process
        process.finished.connect(
            lambda result, p=process: self._on_finished(p, result)
        )

    def _on_finished(self, process, result) -> None:
        if process is not self._process:
            return
        self._process = None
        if result.ok and not result.cancelled:
            rotation = parse_rotation(result.stdout)
            if rotation is not None:
                self.rotation_changed.emit(rotation)
        if self.serial:
            self._timer.start(1000)

    def stop(self) -> None:
        self._timer.stop()
        self.serial = ""
        process = self._process
        self._process = None
        if process is not None and process.is_running:
            process.cancel()


class ControlSidebar(QWidget):
    key_requested = Signal(int, str)
    retry_requested = Signal()
    interval_changed = Signal(int)

    def __init__(self, monitor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ControlSidebar")
        self._landscape = False
        self.setFixedWidth(236)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setObjectName("SidebarScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        self.content = QWidget()
        self.content.setObjectName("SidebarContent")
        self.content.setAutoFillBackground(False)
        scroll.viewport().setAutoFillBackground(False)
        scroll.setWidget(self.content)
        layout = QVBoxLayout(self.content)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self.keys_host = QWidget()
        keys_box = QVBoxLayout(self.keys_host)
        keys_box.setContentsMargins(0, 0, 0, 0)
        keys_box.setSpacing(5)
        title = QLabel("常用按键")
        title.setObjectName("SidebarTitle")
        line = QFrame()
        line.setObjectName("Separator")
        line.setFrameShape(QFrame.Shape.HLine)
        keys_box.addWidget(title)
        keys_box.addWidget(line)
        self.keys_layout = QGridLayout()
        self.keys_layout.setContentsMargins(0, 0, 0, 0)
        self.keys_layout.setSpacing(5)
        keys_box.addLayout(self.keys_layout)

        interval_row = QHBoxLayout()
        interval_label = QLabel("采样间隔")
        interval_label.setObjectName("Muted")
        self.interval_spin = QDoubleSpinBox()
        self.interval_spin.setRange(0.0, 60.0)
        self.interval_spin.setDecimals(1)
        self.interval_spin.setSingleStep(0.1)
        self.interval_spin.setSpecialValueText("禁用")
        self.interval_spin.setToolTip("0.1–60 秒；填 0 禁用自动采样")
        self.interval_spin.valueChanged.connect(
            lambda value: self.interval_changed.emit(round(value * 1000))
        )
        interval_row.addWidget(interval_label)
        interval_row.addWidget(self.interval_spin, 1)
        interval_row.addWidget(QLabel("秒（上限 60）"))
        keys_box.addLayout(interval_row)

        self.buttons: dict[str, QPushButton] = {}
        for label, keycode in KEY_BUTTONS:
            button = QPushButton(label)
            button.setObjectName("SidebarKey")
            button.setMinimumHeight(34)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda _checked=False, code=keycode, name=label: self.key_requested.emit(
                    code, name
                )
            )
            self.buttons[label] = button

        self.telemetry = ControlTelemetry(monitor)
        self.telemetry.layout_changed.connect(
            lambda: QTimer.singleShot(0, self._sync_landscape_height)
        )

        self.body = QGridLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(8)
        layout.addLayout(self.body)

        self.retry_button = QPushButton("重新连接画面")
        self.retry_button.setObjectName("SidebarRetry")
        self.retry_button.setMinimumHeight(34)
        self.retry_button.clicked.connect(self.retry_requested)
        self.retry_button.hide()
        layout.addWidget(self.retry_button)

        self.status = QLabel("打开后按键可用")
        self.status.setObjectName("SidebarHint")
        self.status.setWordWrap(True)
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status)
        layout.addStretch(1)
        self.set_landscape(False)
        self.set_enabled(False)

    def set_landscape(self, landscape: bool) -> None:
        self._landscape = landscape
        self.setProperty("landscape", landscape)
        self.style().unpolish(self)
        self.style().polish(self)
        self.telemetry.set_compact(landscape)
        while self.keys_layout.count():
            item = self.keys_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(self.keys_host)
        columns = 4 if landscape else 1
        for index, button in enumerate(self.buttons.values()):
            button.setMinimumHeight(30 if landscape else 34)
            self.keys_layout.addWidget(button, index // columns, index % columns)
        for column in range(4):
            self.keys_layout.setColumnStretch(
                column,
                1 if column < columns else 0,
            )

        while self.body.count():
            item = self.body.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(self)
        if landscape:
            self.setMinimumWidth(0)
            self.setMaximumWidth(16777215)
            self.setMinimumHeight(0)
            self.setMaximumHeight(360)
            self.body.addWidget(self.keys_host, 0, 0)
            self.body.addWidget(self.telemetry, 0, 1)
            self.body.setColumnStretch(0, 0)
            self.body.setColumnStretch(1, 1)
            QTimer.singleShot(0, self._sync_landscape_height)
        else:
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
            self.setFixedWidth(236)
            self.body.addWidget(self.keys_host, 0, 0)
            self.body.addWidget(self.telemetry, 1, 0)
            self.body.setColumnStretch(0, 1)
            self.body.setColumnStretch(1, 0)

    def _sync_landscape_height(self) -> None:
        if not self._landscape:
            return
        target = self.content.sizeHint().height() + 4
        self.setFixedHeight(max(150, min(340, target)))

    def set_enabled(self, enabled: bool) -> None:
        for button in self.buttons.values():
            button.setEnabled(enabled)

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def set_retry_visible(self, visible: bool) -> None:
        self.retry_button.setVisible(visible)

    def set_interval(self, interval_ms: int) -> None:
        self.interval_spin.blockSignals(True)
        self.interval_spin.setValue(max(0, interval_ms) / 1000)
        self.interval_spin.blockSignals(False)


class ControlWindow(QMainWindow):
    """Independent phone control window for exactly one device."""

    closed = Signal()

    def __init__(self, context, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.manager = ScrcpyWindowProcess(
            context.adb,
            vendor_scrcpy_exe(),
            self,
            max_fps=60,
            max_size=context.config.scrcpy_max_size,
        )
        # Reuse the application-wide monitor.  Creating a second monitor here
        # doubled the shell load (two heavy metric scripts every 2 s) and made
        # taps/swipes stutter while the control window was open.
        self.monitor = context.metrics
        self.rotation_watcher = _OrientationWatcher(context.adb, self)
        self._serial = ""
        self._closing = False
        self._native_hwnd = 0
        self._embed_pending = False
        self._landscape = False
        self._rotation: int | None = None
        self._log_lines: list[str] = []
        self.setWindowTitle("手机控制")
        self.resize(820, 900)
        self.setMinimumSize(620, 640)

        self._fit_timer = QTimer(self)
        self._fit_timer.setInterval(250)
        self._fit_timer.timeout.connect(self._position_native)

        central = QWidget()
        self.body_layout = QBoxLayout(
            QBoxLayout.Direction.LeftToRight,
            central,
        )
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(0)

        self.sidebar = ControlSidebar(self.monitor)
        self.sidebar.set_interval(context.config.metrics_interval_ms)
        self.telemetry = self.sidebar.telemetry
        self.video_area = QWidget()
        self.video_area.setObjectName("NativeVideoHost")
        self.body_layout.addWidget(self.sidebar)
        self.body_layout.addWidget(self.video_area, 1)
        self.setCentralWidget(central)

        self.sidebar.key_requested.connect(self._send_key)
        self.sidebar.retry_requested.connect(self._restart)
        self.sidebar.interval_changed.connect(self._on_interval_changed)
        self.manager.window_ready.connect(self._embed)
        self.manager.started.connect(self._on_started)
        self.manager.failed.connect(self._on_failed)
        self.manager.finished.connect(self._on_finished)
        self.manager.log.connect(self._on_log)
        self.rotation_watcher.rotation_changed.connect(self._apply_rotation)
        context.metrics_interval_changed.connect(self._on_global_interval)

    @property
    def serial(self) -> str:
        return self._serial

    def show_for(self, serial: str) -> None:
        same_device = self._serial == serial
        self._serial = serial
        self.setWindowTitle(f"手机控制 - {serial}")
        self.sidebar.set_enabled(False)
        if not same_device:
            self._log_lines.clear()
            self.telemetry.set_waiting()
        self.monitor.set_device(serial, self.context.config.metrics_interval_ms)
        self.rotation_watcher.set_serial(serial)
        self.show()
        self.raise_()
        self.activateWindow()
        if self.manager.running and self.manager.serial == serial:
            if self._native_hwnd:
                self.sidebar.set_status("已连接 · 按键可用")
            elif self.manager.ready and self.manager.hwnd:
                self._embed(self.manager.hwnd)
            else:
                self.sidebar.set_status("正在启动控制通道…")
            return
        self.sidebar.set_retry_visible(False)
        self.sidebar.set_status("正在启动控制通道…")
        self.manager.start(serial)

    def _apply_rotation(self, rotation: int) -> None:
        if rotation == self._rotation:
            return
        self._rotation = rotation
        self._apply_orientation(rotation % 2 == 1)

    def _on_interval_changed(self, interval_ms: int) -> None:
        self.context.set_metrics_interval(interval_ms)

    def _on_global_interval(self, interval_ms: int) -> None:
        self.sidebar.set_interval(interval_ms)
        self.monitor.set_interval(interval_ms)
        self.telemetry.updated.setText(
            "自动采样已禁用" if interval_ms <= 0 else "等待采样"
        )

    def _apply_orientation(self, landscape: bool) -> None:
        if self._landscape == landscape:
            return
        self._landscape = landscape
        self.body_layout.setDirection(
            QBoxLayout.Direction.TopToBottom
            if landscape
            else QBoxLayout.Direction.LeftToRight
        )
        self.sidebar.set_landscape(landscape)
        if not self.isMaximized() and not self.isFullScreen():
            QTimer.singleShot(0, lambda: self._resize_for_orientation(landscape))
        QTimer.singleShot(0, self._position_native)

    def _resize_for_orientation(self, landscape: bool) -> None:
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        width = min(1280 if landscape else 820, available.width() - 60)
        height = min(820 if landscape else 900, available.height() - 80)
        self.resize(
            max(self.minimumWidth(), width),
            max(self.minimumHeight(), height),
        )

    def _restart(self) -> None:
        if not self._serial:
            return
        self.sidebar.set_retry_visible(False)
        self.sidebar.set_enabled(False)
        self.sidebar.set_status("正在重新连接画面…")
        self.telemetry.set_waiting()
        self.monitor.set_device(
            self._serial,
            self.context.config.metrics_interval_ms,
        )
        if self.manager.running:
            self.manager.stop()
        self._log_lines.clear()
        self.manager.start(self._serial)

    def _embed(self, hwnd: int) -> None:
        if sys.platform != "win32" or not hwnd:
            self.sidebar.set_status("当前系统不支持嵌入画面")
            return
        self._native_hwnd = hwnd
        self._embed_pending = True
        try:
            user32 = ctypes.windll.user32
            user32.GetWindowLongW.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
            user32.GetWindowLongW.restype = ctypes.c_long
            user32.SetWindowLongW.argtypes = [
                ctypes.wintypes.HWND,
                ctypes.c_int,
                ctypes.c_long,
            ]
            user32.SetWindowLongW.restype = ctypes.c_long
            user32.SetParent.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.HWND]
            user32.SetParent.restype = ctypes.wintypes.HWND
            user32.GetParent.argtypes = [ctypes.wintypes.HWND]
            user32.GetParent.restype = ctypes.wintypes.HWND
            user32.GetAncestor.argtypes = [ctypes.wintypes.HWND, ctypes.c_uint]
            user32.GetAncestor.restype = ctypes.wintypes.HWND
            user32.GetWindowRect.argtypes = [
                ctypes.wintypes.HWND,
                ctypes.POINTER(ctypes.wintypes.RECT),
            ]
            user32.GetWindowRect.restype = ctypes.wintypes.BOOL
            user32.ShowWindow.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
            user32.ShowWindow.restype = ctypes.wintypes.BOOL
            original_style = int(user32.GetWindowLongW(hwnd, -16))
            # Hide while changing the window tree: a mouse event arriving
            # before scrcpy has initialized its content rectangle crashes it.
            user32.ShowWindow(hwnd, 0)
            style = (
                original_style
                & ~(0x80000000 | 0x00C00000 | 0x00040000 | 0x00080000)
            ) | 0x40000000
            signed_style = ctypes.c_long(style & 0xFFFFFFFF).value
            user32.SetWindowLongW(hwnd, -16, signed_style)
            user32.SetParent(hwnd, int(self.winId()))
            self._position_native()
            parent = int(user32.GetParent(hwnd) or 0)
            ancestor = int(user32.GetAncestor(hwnd, 1) or 0)
            embedded = (signed_style & 0x40000000) and int(self.winId()) in (
                parent,
                ancestor,
            )
            if embedded:
                self.sidebar.set_enabled(False)
                self.sidebar.set_retry_visible(False)
                self.sidebar.set_status("正在显示画面…")
                QTimer.singleShot(120, lambda h=hwnd: self._show_embedded(h))
            else:
                self._native_hwnd = 0
                self._show_standalone(hwnd, original_style)
        except Exception as exc:
            self._native_hwnd = 0
            self._embed_pending = False
            try:
                ctypes.windll.user32.SetParent(hwnd, 0)
                ctypes.windll.user32.ShowWindow(hwnd, 5)
            except Exception:
                pass
            self.sidebar.set_status(f"嵌入画面失败：{exc}")

    def _show_embedded(self, hwnd: int) -> None:
        if (
            self._native_hwnd != hwnd
            or not self.manager.running
            or self.manager.serial != self._serial
        ):
            self._embed_pending = False
            return
        self._embed_pending = False
        try:
            ctypes.windll.user32.ShowWindow(hwnd, 5)
        except Exception:
            pass
        self._position_native()
        self._fit_timer.start()
        self.sidebar.set_enabled(True)
        self.sidebar.set_retry_visible(False)
        self.sidebar.set_status("已连接 · 按键可用")

    def _show_standalone(self, hwnd: int, original_style: int) -> None:
        self._embed_pending = False
        try:
            user32 = ctypes.windll.user32
            user32.SetWindowLongW(
                hwnd,
                -16,
                ctypes.c_long(original_style & 0xFFFFFFFF).value,
            )
            user32.SetParent(hwnd, 0)
            screen = self.screen() or QGuiApplication.primaryScreen()
            if screen is not None:
                available = screen.availableGeometry()
                rect = ctypes.wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                width = max(320, rect.right - rect.left)
                height = max(400, rect.bottom - rect.top)
                width = min(width, available.width() - 80)
                height = min(height, available.height() - 80)
                x = available.x() + (available.width() - width) // 2
                y = available.y() + (available.height() - height) // 2
                user32.SetWindowPos(
                    hwnd,
                    0,
                    x,
                    y,
                    width,
                    height,
                    0x0004 | 0x0040,
                )
            user32.ShowWindow(hwnd, 5)
            self.sidebar.set_status("无法嵌入画面，已单独打开")
        except Exception as exc:
            self.sidebar.set_status(f"嵌入画面失败：{exc}")

    def _position_native(self) -> None:
        if not self._native_hwnd or sys.platform != "win32":
            return
        try:
            user32 = ctypes.windll.user32
            user32.SetWindowPos.argtypes = [
                ctypes.wintypes.HWND,
                ctypes.wintypes.HWND,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_uint,
            ]
            point = self.video_area.mapTo(self, QPoint(0, 0))
            ratio = self.devicePixelRatioF()
            width = max(1, round(self.video_area.width() * ratio))
            height = max(1, round(self.video_area.height() * ratio))
            flags = 0x0004 | 0x0020
            if not self._embed_pending:
                flags |= 0x0040
            user32.SetWindowPos(
                self._native_hwnd,
                0,
                round(point.x() * ratio),
                round(point.y() * ratio),
                width,
                height,
                flags,
            )
        except Exception:
            pass

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_native()
        QTimer.singleShot(0, self._position_native)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._position_native)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and not self.isMinimized():
            QTimer.singleShot(0, self._restore_native)

    def _restore_native(self) -> None:
        if not self._native_hwnd or self._embed_pending or sys.platform != "win32":
            return
        try:
            ctypes.windll.user32.ShowWindow(self._native_hwnd, 5)
        except Exception:
            pass
        self._fit_timer.start()
        self._position_native()

    def _on_started(self) -> None:
        self.sidebar.set_status("scrcpy 已启动，等待画面…")

    def _on_log(self, text: str) -> None:
        for line in text.splitlines():
            line = line.strip()
            if line:
                self._log_lines.append(line)
        if len(self._log_lines) > 40:
            self._log_lines = self._log_lines[-40:]

    def _last_error(self) -> str:
        return self._log_lines[-1] if self._log_lines else ""

    def _on_failed(self, message: str) -> None:
        self.sidebar.set_enabled(False)
        self.sidebar.set_retry_visible(True)
        self.sidebar.set_status(f"启动失败：{message}")
        self.statusBar().showMessage(message)
        self._fit_timer.stop()
        self._native_hwnd = 0
        self._embed_pending = False

    def _on_finished(self, exit_code: int) -> None:
        if self._closing:
            return
        self._fit_timer.stop()
        self._native_hwnd = 0
        self._embed_pending = False
        self.sidebar.set_enabled(False)
        self.sidebar.set_retry_visible(True)
        detail = self._last_error()
        message = f"画面已断开（scrcpy 退出码 {exit_code}）"
        self.sidebar.set_status(f"{message}\n点击上方按钮重新连接")
        self.statusBar().showMessage(detail or message)

    def _send_key(self, keycode: int, label: str) -> None:
        if not self._serial:
            return
        try:
            self.context.adb.run(
                self._serial,
                "shell",
                "input",
                "keyevent",
                str(keycode),
                timeout_ms=5000,
                record=False,
            )
            self.sidebar.set_status(f"已发送：{label}")
            QTimer.singleShot(1200, self._restore_hint)
        except Exception as exc:
            self.sidebar.set_status(f"按键失败：{exc}")

    def _restore_hint(self) -> None:
        if not self._closing and self.manager.running:
            self.sidebar.set_status("已连接 · 按键可用")

    def closeEvent(self, event) -> None:
        self._closing = True
        for signal, slot in (
            (self.manager.window_ready, self._embed),
            (self.manager.started, self._on_started),
            (self.manager.failed, self._on_failed),
            (self.manager.finished, self._on_finished),
            (self.manager.log, self._on_log),
        ):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._fit_timer.stop()
        self.rotation_watcher.stop()
        self.manager.stop()
        self._native_hwnd = 0
        self._embed_pending = False
        super().closeEvent(event)
        self.closed.emit()
