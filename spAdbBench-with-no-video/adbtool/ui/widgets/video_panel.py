from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class VideoPanel(QWidget):
    """Small placeholder that keeps the main-window signal contract."""

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
        self._session = session
        self.preview_only = preview_only
        self.device_serial = ""
        self._preview_enabled = True
        self._state = "无视频"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        label = QLabel("此版本不包含视频预览")
        label.setObjectName("Muted")
        label.setWordWrap(True)
        layout.addWidget(label)
        layout.addStretch(1)

    def set_preview_enabled(self, enabled: bool) -> None:
        self._preview_enabled = bool(enabled)

    def set_frame_for(self, serial: str, image) -> None:
        return

    def set_state(self, state: str) -> None:
        self._state = state

    def set_device(self, serial: str | None) -> None:
        self.device_serial = serial or ""

    def refresh(self) -> None:
        return
