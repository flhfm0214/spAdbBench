from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QTimer,
    Signal,
    Qt,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ToastBanner(QFrame):
    """In-window notification that never uses a system tray balloon."""

    dismissed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMaximumWidth(460)
        self.setMinimumWidth(300)
        self._duration_ms = 2000
        self._fade: QPropertyAnimation | None = None
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(1.0)
        self.setGraphicsEffect(self._effect)

        self.title_label = QLabel("发现新设备")
        self.title_label.setObjectName("ToastTitle")
        self.detail_label = QLabel("")
        self.detail_label.setObjectName("ToastText")
        self.detail_label.setWordWrap(True)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.detail_label)

        self.close_button = QPushButton("×")
        self.close_button.setObjectName("ToastClose")
        self.close_button.setFixedSize(24, 24)
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.setToolTip("关闭提示")
        self.close_button.clicked.connect(self.dismiss)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 10, 10)
        layout.setSpacing(10)
        layout.addLayout(text_layout, 1)
        layout.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.dismiss)
        self.hide()

    def show_message(self, detail: str, duration_ms: int = 2000) -> None:
        if self._fade is not None:
            self._fade.stop()
            self._fade = None
        self._effect.setOpacity(1.0)
        self.detail_label.setText(detail)
        self._duration_ms = max(500, int(duration_ms))
        self.adjustSize()
        self.show()
        self.raise_()
        self.timer.start(self._duration_ms)

    def dismiss(self, animate: bool = True) -> None:
        self.timer.stop()
        if not self.isVisible():
            return
        if not animate:
            self._finish_hide()
            return
        if self._fade is not None:
            self._fade.stop()
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(180)
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.setEasingCurve(QEasingCurve.Type.InCubic)
        self._fade.finished.connect(self._finish_hide)
        self._fade.start()

    def _finish_hide(self) -> None:
        self._fade = None
        self.hide()
        self._effect.setOpacity(1.0)
        self.dismissed.emit()
