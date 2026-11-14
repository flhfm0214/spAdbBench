from pathlib import Path

from adbtool.channels.scrcpy_window import ScrcpyWindowProcess
from adbtool.infrastructure.config import AppConfig, ConfigStore
from adbtool.infrastructure.parsers import DeviceInfo
from adbtool.services.adb import AdbService
from adbtool.services.devices import DeviceService
from adbtool.services.metrics import MetricsMonitor
from adbtool.ui.context import AppContext
from adbtool.ui.control_window import _OrientationWatcher
from adbtool.ui.main_window import PROJECT_URL, MainWindow
from adbtool.ui.pages.device_page import DevicePage
from adbtool.ui.pages.log_page import LogPage
from adbtool.ui.status_bus import StatusBus
from adbtool.ui.widgets.video_panel import VideoPanel


def make_window(qtbot, tmp_path):
    config = AppConfig(adb_path=str(Path("platform-tools") / "adb.exe"))
    store = ConfigStore(tmp_path)
    adb = AdbService(Path(config.adb_path))
    devices = DeviceService(adb)
    status = StatusBus()
    context = AppContext(config, store, adb, devices, status)
    window = MainWindow(context, auto_refresh=False)
    qtbot.addWidget(window)
    return window, context


def test_main_window_constructs_with_navigation_and_dock(qtbot, tmp_path):
    window, _context = make_window(qtbot, tmp_path)
    window.show()

    assert window.nav.count() == 13
    assert window.stack.count() == window.nav.count()
    assert isinstance(window.stack.widget(0), DevicePage)
    assert isinstance(window.stack.widget(12), LogPage)
    assert window.device_combo is not None
    assert "github项目地址:" in window.project_link.text()
    assert "spAdbBench" in window.project_link.text()
    assert "font-size:12px" in window.project_link.text()
    assert "font-size:13px" in window.project_link.text()
    assert "text-decoration:underline" in window.project_link.text()
    assert "color:#ffffff" in window.project_link.text()
    assert window.project_link.toolTip() == PROJECT_URL
    assert window.project_icon.icon().isNull() is False
    assert window.device_dock.isVisible() is True
    assert window.device_dock.windowTitle() == "屏幕预览"
    assert window.device_dock.minimumWidth() == 340
    assert window.device_dock.maximumWidth() == 340
    assert isinstance(window.video_panel, VideoPanel)
    assert window.video_panel.preview_only is True
    assert window.video_panel._session is _context.scrcpy


def test_preview_dock_is_fixed_without_close_button(qtbot, tmp_path):
    from PySide6.QtWidgets import QDockWidget

    window, _context = make_window(qtbot, tmp_path)
    window.show()

    features = window.device_dock.features()
    assert features == QDockWidget.DockWidgetFeature.NoDockWidgetFeatures
    assert not features & QDockWidget.DockWidgetFeature.DockWidgetClosable
    assert not features & QDockWidget.DockWidgetFeature.DockWidgetFloatable
    assert not features & QDockWidget.DockWidgetFeature.DockWidgetMovable
    assert not hasattr(window, "dock_action")


def test_window_restore_refreshes_preview(qtbot, tmp_path):
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication

    window, _context = make_window(qtbot, tmp_path)
    window.show()
    calls: list[bool] = []
    window.video_panel.refresh = lambda: calls.append(True)

    QApplication.sendEvent(window, QEvent(QEvent.Type.WindowStateChange))
    qtbot.wait(20)

    assert calls == [True]


def test_device_selection_starts_one_fps_preview(qtbot, tmp_path):
    window, context = make_window(qtbot, tmp_path)
    calls: list[str] = []
    context.scrcpy.start = calls.append

    window._select_device(DeviceInfo(serial="ABC", state="device"))

    assert calls == ["ABC"]
    assert context.scrcpy.max_fps == 1


def test_device_change_stops_old_scrcpy_session(qtbot, tmp_path):
    window, context = make_window(qtbot, tmp_path)
    stopped: list[bool] = []
    started: list[str] = []
    context.scrcpy._serial = "OLD"
    context.scrcpy.stop = lambda: stopped.append(True)
    context.scrcpy.start = started.append

    window._select_device(DeviceInfo(serial="NEW", state="device"))

    assert stopped == [True]
    assert started == ["NEW"]
    assert window.video_panel.device_serial == "NEW"


def _stub_control_window(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        ScrcpyWindowProcess,
        "start",
        lambda self, serial: calls.append(serial) or True,
    )
    monkeypatch.setattr(MetricsMonitor, "set_device", lambda *args, **kwargs: None)
    monkeypatch.setattr(_OrientationWatcher, "set_serial", lambda *args, **kwargs: None)
    return calls


def test_open_control_window_uses_selected_device(qtbot, tmp_path, monkeypatch):
    window, context = make_window(qtbot, tmp_path)
    calls = _stub_control_window(monkeypatch)
    context.current_device = DeviceInfo(serial="ABC", state="device")
    window.video_panel.set_device("ABC")
    window.show()

    window.video_panel.open_window_button.click()

    assert calls == ["ABC"]
    assert window.video_panel.isHidden() is False
    assert "ABC" in window.control_windows
    window.control_windows["ABC"].close()
    assert window.control_windows == {}


def test_multiple_control_windows_stay_open_per_device(qtbot, tmp_path, monkeypatch):
    window, context = make_window(qtbot, tmp_path)
    calls = _stub_control_window(monkeypatch)
    context.scrcpy.start = lambda serial: True
    window.show()

    for serial in ("ABC", "XYZ"):
        context.current_device = DeviceInfo(serial=serial, state="device")
        window.video_panel.set_device(serial)
        window._open_control_window()

    assert calls == ["ABC", "XYZ"]
    assert set(window.control_windows) == {"ABC", "XYZ"}
    assert (
        window.control_windows["ABC"].manager
        is not window.control_windows["XYZ"].manager
    )

    window._select_device(DeviceInfo(serial="XYZ", state="device"))

    assert set(window.control_windows) == {"ABC", "XYZ"}

    window._prune_control_windows([DeviceInfo(serial="XYZ", state="device")])

    assert set(window.control_windows) == {"XYZ"}
    window.close()


def test_theme_switch_updates_config_and_stylesheet(qtbot, tmp_path):
    from PySide6.QtWidgets import QApplication

    window, context = make_window(qtbot, tmp_path)
    window.set_theme("dark")

    assert context.config.theme == "dark"
    assert context.config_store.load().theme == "dark"
    assert "#4f8ef7" in QApplication.instance().styleSheet()


def test_device_table_receives_devices(qtbot, tmp_path):
    window, context = make_window(qtbot, tmp_path)
    window.show()

    context.set_devices(
        [
            DeviceInfo(serial="ABC", state="device", model="Pixel 7"),
            DeviceInfo(serial="XYZ", state="unauthorized"),
        ]
    )

    page = window.stack.widget(0)
    assert isinstance(page, DevicePage)
    assert page.table.rowCount() == 2
    assert page.table.item(0, 0).text() == "ABC"


def test_action_buttons_fit_at_minimum_window_width(qtbot, tmp_path):
    window, _context = make_window(qtbot, tmp_path)
    window.resize(980, 640)
    window.show()
    qtbot.wait(20)

    window.nav.setCurrentRow(1)
    qtbot.wait(20)
    apps_page = window.stack.widget(1)
    for button in apps_page.action_buttons.values():
        assert button.width() >= button.sizeHint().width(), button.text()
    assert apps_page.select_all_button.width() >= apps_page.select_all_button.sizeHint().width()

    window.nav.setCurrentRow(3)
    qtbot.wait(20)
    display_page = window.stack.widget(3)
    for button in (
        display_page.set_size_button,
        display_page.reset_size_button,
        display_page.set_density_button,
        display_page.reset_density_button,
    ):
        assert button.width() >= button.sizeHint().width(), button.text()
