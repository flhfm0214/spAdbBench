from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class StatusBus(QObject):
    message = Signal(str, str)

    def info(self, text: str) -> None:
        self.message.emit(text, "info")

    def success(self, text: str) -> None:
        self.message.emit(text, "success")

    def error(self, text: str) -> None:
        self.message.emit(text, "error")
