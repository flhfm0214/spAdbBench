from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..infrastructure.parsers import DeviceInfo
from .context import AppContext


class BasePage(QWidget):
    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context

    def on_activated(self) -> None:
        pass

    def on_deactivated(self) -> None:
        pass

    def on_device_changed(self, device: DeviceInfo | None) -> None:
        pass

    def shutdown(self) -> None:
        pass


class PlaceholderPage(BasePage):
    def __init__(self, context: AppContext, title: str, description: str) -> None:
        super().__init__(context)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(8)

        heading = QLabel(title)
        heading.setObjectName("SectionTitle")
        copy = QLabel(description)
        copy.setObjectName("Muted")
        copy.setWordWrap(True)

        layout.addWidget(heading)
        layout.addWidget(copy)
        layout.addStretch(1)
