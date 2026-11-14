from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication, QLabel

# These labels paint video/screenshot content and own their mouse handling.
_SKIP_OBJECT_NAMES = {
    "VideoCanvas",
    "ScreenshotPreview",
    "ProjectLink",
    "ProjectLinkIcon",
}


def _make_selectable(label: QLabel) -> None:
    if label.objectName() in _SKIP_OBJECT_NAMES:
        return
    if not label.pixmap().isNull():
        return
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
    label.setCursor(Qt.CursorShape.IBeamCursor)


class _SelectableLabelFilter(QObject):
    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.Show and isinstance(watched, QLabel):
            _make_selectable(watched)
        return False


def install_selectable_labels(app: QApplication | None = None) -> None:
    """Make all informational labels selectable, including future dialogs.

    A single application event filter keeps late-created labels (settings,
    dialogs, page refreshes) selectable without touching each widget.
    """
    app = app or QApplication.instance()
    if app is None:
        return
    if app.findChild(_SelectableLabelFilter) is None:
        app.installEventFilter(_SelectableLabelFilter(app))
    for widget in app.allWidgets():
        if isinstance(widget, QLabel):
            _make_selectable(widget)
