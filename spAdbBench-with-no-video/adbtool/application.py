from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import __version__
from .infrastructure.adb_locator import AdbNotFoundError, resolve_adb
from .infrastructure.config import ConfigStore
from .infrastructure.execution_log import ExecutionLog
from .infrastructure.paths import default_execution_log, project_root, resource_root
from .services.adb import AdbService
from .services.devices import DeviceService
from .ui.context import AppContext
from .ui.main_window import MainWindow
from .ui.status_bus import StatusBus
from .ui.widgets.selectable import install_selectable_labels


def build_app(argv: list[str] | None = None) -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("spAdbBench-no-video")
    app.setApplicationDisplayName("spAdbBench 无视频版")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("spAdbBench")
    app.setStyle("Fusion")
    icon_path = resource_root() / "packaging" / "spAdbBench.png"
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    install_selectable_labels(app)
    return app


def build_context() -> AppContext:
    root = project_root()
    store = ConfigStore(root)
    config = store.load()
    status = StatusBus()

    try:
        adb_path = resolve_adb(config, root)
        error = ""
    except AdbNotFoundError as exc:
        adb_path = Path(config.adb_path or "adb")
        error = str(exc)

    adb = AdbService(adb_path, execution_log=ExecutionLog(default_execution_log()))
    devices = DeviceService(adb)
    context = AppContext(config, store, adb, devices, status)
    if error:
        status.error(error)
    return context


def run(argv: list[str] | None = None) -> int:
    app = build_app(argv)
    context = build_context()
    window = MainWindow(context, auto_refresh=True)
    window.show()
    return app.exec()
