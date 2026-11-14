from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class ScrcpySession(QObject):
    """No-video placeholder for :class:`AppContext`.

    Keeps the same signal surface as the video session so the rest of the UI
    can stay unchanged, but never loads wetest, av, cv2, or numpy.
    """

    frame_for_serial = Signal(str, object)
    state_changed = Signal(str)
    error = Signal(str)
    control_ready = Signal(object)

    def __init__(self, config=None, adb=None, parent=None, max_fps: int = 1) -> None:
        super().__init__(parent)
        self.config = config
        self.adb = adb
        self.max_fps = max_fps
        self.serial = ""
        self.state = "无视频"
        self.server = None

    def start(self, serial: str) -> bool:
        self.serial = serial or ""
        self.state = "无视频"
        return False

    def stop(self) -> None:
        self.serial = ""
        self.state = "无视频"
        self.server = None
