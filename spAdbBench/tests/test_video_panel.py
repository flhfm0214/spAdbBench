from __future__ import annotations

import pytest
from PySide6.QtCore import QObject, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QImage

from adbtool.channels.scrcpy_control import map_click
from adbtool.ui.widgets.video_panel import VideoPanel


class FakeSession(QObject):
    frame_ready = Signal(object)
    state_changed = Signal(str)
    error = Signal(str)
    control_ready = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.last_tap: tuple[float, float] | None = None
        self.last_swipe: tuple[float, float, float, float, int] | None = None
        self.started: str | None = None
        self.stopped = False
        self._serial = ""

    @property
    def serial(self) -> str:
        return self._serial

    def tap_norm(self, nx: float, ny: float) -> None:
        self.last_tap = (nx, ny)

    def swipe_norm(self, nx: float, ny: float, ex: float, ey: float, duration_ms: int) -> None:
        self.last_swipe = (nx, ny, ex, ey, duration_ms)

    def start(self, serial: str) -> None:
        self._serial = serial
        self.started = serial

    def stop(self) -> None:
        self.stopped = True


def make_image(width: int = 1000, height: int = 500) -> QImage:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(0xFF336699)
    return image


def make_panel(qtbot) -> tuple[VideoPanel, FakeSession]:
    session = FakeSession()
    panel = VideoPanel(session)
    qtbot.addWidget(panel)
    panel.resize(400, 400)
    panel.show()
    qtbot.wait(20)
    panel.set_device("ABC")
    panel.set_frame(make_image())
    qtbot.wait(20)
    return panel, session


def test_video_label_size_hint_ignores_large_frame(qtbot):
    from PySide6.QtCore import QSize

    panel, _session = make_panel(qtbot)
    panel.resize(1600, 1000)
    panel.set_frame(make_image(4000, 3000))
    qtbot.wait(20)

    assert panel.image_label.sizeHint() == QSize(320, 240)
    assert panel.image_label.minimumSizeHint() == QSize(0, 0)
    assert panel.image_label.minimumWidth() == 0
    assert panel.image_label.minimumHeight() == 0


def test_video_panel_maps_click(qtbot):
    panel, session = make_panel(qtbot)
    label = panel.image_label
    center = QPoint(label.width() // 2, label.height() // 2)

    qtbot.mouseClick(label, Qt.MouseButton.LeftButton, pos=center)

    assert session.last_tap == pytest.approx((0.5, 0.5), abs=0.01)


def test_letterbox_click_is_ignored(qtbot):
    panel, session = make_panel(qtbot)
    label = panel.image_label
    image_rect = QRect(0, 0, 1000, 500)
    point = QPoint(label.width() // 2, 2)

    assert map_click(point, label.size(), image_rect) is None
    qtbot.mouseClick(label, Qt.MouseButton.LeftButton, pos=point)

    assert session.last_tap is None


def test_drag_below_threshold_is_tap(qtbot):
    panel, session = make_panel(qtbot)
    label = panel.image_label
    start = QPoint(label.width() // 2, label.height() // 2)
    end = start + QPoint(2, 0)

    qtbot.mousePress(label, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(label, end)
    qtbot.mouseRelease(label, Qt.MouseButton.LeftButton, pos=end)

    assert session.last_tap is not None
    assert session.last_swipe is None


def test_drag_emits_swipe(qtbot):
    panel, session = make_panel(qtbot)
    label = panel.image_label
    start = QPoint(int(label.width() * 0.25), label.height() // 2)
    end = QPoint(int(label.width() * 0.75), label.height() // 2)

    qtbot.mousePress(label, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(label, end)
    qtbot.mouseRelease(label, Qt.MouseButton.LeftButton, pos=end)

    assert session.last_swipe is not None
    assert session.last_swipe[0] < session.last_swipe[2]
    assert session.last_swipe[4] >= 0


def test_device_change_clears_old_frame(qtbot):
    panel, _session = make_panel(qtbot)
    assert not panel.image_label.pixmap().isNull()

    panel.set_device("XYZ")

    assert panel.device_serial == "XYZ"
    assert panel.image_label.pixmap().isNull()
    assert panel.state == "待连接"


def test_state_controls_reconnect_and_disconnect(qtbot):
    panel, _session = make_panel(qtbot)

    panel.set_state("已连接")
    assert panel.reconnect_button.isEnabled() is False
    assert panel.disconnect_button.isEnabled() is True

    panel.set_state("已停止")
    assert panel.reconnect_button.isEnabled() is True
    assert panel.disconnect_button.isEnabled() is False


def test_device_without_selection_disables_reconnect(qtbot):
    panel, _session = make_panel(qtbot)
    panel.set_state("已停止")

    panel.set_device(None)

    assert panel.device_serial == ""
    assert panel.reconnect_button.isEnabled() is False
    assert panel.image_label.pixmap().isNull()


def test_preview_only_shows_prominent_cta_and_ignores_click(qtbot):
    session = FakeSession()
    panel = VideoPanel(session, preview_only=True)
    qtbot.addWidget(panel)
    panel.resize(400, 400)
    panel.show()
    panel.set_device("ABC")
    panel.set_frame(make_image())
    qtbot.wait(20)

    assert panel.preview_only is True
    assert panel.open_window_button.text() == "打开独立窗口操作设备"
    assert panel.open_window_button.objectName() == "Primary"
    assert panel.reconnect_button.isVisible() is False
    label = panel.image_label
    qtbot.mouseClick(
        label,
        Qt.MouseButton.LeftButton,
        pos=QPoint(label.width() // 2, label.height() // 2),
    )
    assert session.last_tap is None


def test_refresh_restores_pixmap_after_it_was_cleared(qtbot):
    panel, _session = make_panel(qtbot)
    panel.image_label.clear()
    assert panel.image_label.pixmap().isNull()

    panel.refresh()

    assert panel.image_label.pixmap().isNull() is False


def test_buttons_emit_intents(qtbot):
    panel, _session = make_panel(qtbot)
    panel.set_state("已停止")

    with qtbot.waitSignal(panel.reconnect, timeout=1000):
        panel.reconnect_button.click()

    panel.set_state("已连接")
    with qtbot.waitSignal(panel.disconnect_requested, timeout=1000):
        panel.disconnect_button.click()

    with qtbot.waitSignal(panel.open_window, timeout=1000):
        panel.open_window_button.click()
