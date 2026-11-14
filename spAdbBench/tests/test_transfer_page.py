from pathlib import Path

from adbtool.infrastructure.config import AppConfig, ConfigStore
from adbtool.services.adb import AdbService
from adbtool.services.devices import DeviceService
from adbtool.ui.context import AppContext
from adbtool.ui.main_window import MainWindow
from adbtool.ui.pages.transfer_page import TransferPage
from adbtool.ui.status_bus import StatusBus


def make_window(qtbot, tmp_path):
    config = AppConfig(adb_path=str(Path("platform-tools") / "adb.exe"))
    store = ConfigStore(tmp_path)
    adb = AdbService(Path(config.adb_path))
    devices = DeviceService(adb)
    context = AppContext(config, store, adb, devices, StatusBus())
    window = MainWindow(context, auto_refresh=False)
    qtbot.addWidget(window)
    return window, context


def test_transfer_page_is_third_navigation_page(qtbot, tmp_path):
    window, _context = make_window(qtbot, tmp_path)
    assert isinstance(window.stack.widget(2), TransferPage)
