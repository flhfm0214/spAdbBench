from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QPushButton

from adbtool.infrastructure.config import AppConfig, ConfigStore
from adbtool.services.adb import AdbService
from adbtool.services.devices import DeviceService
from adbtool.services.script import ScriptLineResult, ScriptRunResult
from adbtool.ui.context import AppContext
from adbtool.ui.main_window import MainWindow
from adbtool.ui.pages.script_page import ScriptPage
from adbtool.ui.status_bus import StatusBus


class FakeJob(QObject):
    line = Signal(object)
    finished = Signal(object)
    state = Signal(str)

    def __init__(self, adb_path, serial, source) -> None:
        super().__init__()
        self.adb_path = adb_path
        self.serial = serial
        self.source = source
        self.started = False
        self.cancelled = False

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True

    def wait(self, _timeout=2000) -> None:
        pass


def make_window(qtbot, tmp_path):
    config = AppConfig(adb_path=str(Path("platform-tools") / "adb.exe"))
    store = ConfigStore(tmp_path)
    adb = AdbService(Path(config.adb_path))
    devices = DeviceService(adb)
    context = AppContext(config, store, adb, devices, StatusBus())
    window = MainWindow(context, auto_refresh=False)
    qtbot.addWidget(window)
    return window, context


def test_script_page_is_ninth_navigation_page(qtbot, tmp_path):
    window, _context = make_window(qtbot, tmp_path)

    assert isinstance(window.stack.widget(9), ScriptPage)
    assert window.nav.count() == 13


def test_run_waits_for_confirmation_and_starts_job(qtbot, tmp_path, monkeypatch):
    window, _context = make_window(qtbot, tmp_path)
    page = window.stack.widget(9)
    page._serial = "ABC"
    page._update_controls()
    page.editor.setPlainText("echo hello\nadb devices\n")
    jobs = []
    page.job_factory = lambda adb_path, serial, source: jobs.append(
        FakeJob(adb_path, serial, source)
    ) or jobs[-1]
    specs = []

    monkeypatch.setattr(page, "_confirm", lambda spec: specs.append(spec) or False)
    page.run_button.click()
    assert specs[-1].key == "script.run"
    assert jobs == []

    monkeypatch.setattr(page, "_confirm", lambda _spec: True)
    page.run_button.click()

    assert len(jobs) == 1
    assert jobs[0].started is True
    assert jobs[0].serial == "ABC"
    assert "adb devices" in jobs[0].source

    jobs[0].line.emit(ScriptLineResult(2, "command", "devices", True, "ok"))
    assert page.table.rowCount() == 1
    assert page.table.item(0, 2).text() == "devices"

    jobs[0].finished.emit(ScriptRunResult(0, executed_commands=["devices"]))
    assert page._running is False
    assert "已完成" in page.status_label.text()


def test_empty_script_does_not_start(qtbot, tmp_path, monkeypatch):
    window, _context = make_window(qtbot, tmp_path)
    page = window.stack.widget(9)
    page._serial = "ABC"
    page._update_controls()
    jobs = []
    page.job_factory = lambda *args: jobs.append(args) or FakeJob(*args)

    page.run_button.click()

    assert jobs == []
    assert "为空" in page.message_label.text()


def test_double_click_opens_complete_result_detail(qtbot, tmp_path, monkeypatch):
    window, _context = make_window(qtbot, tmp_path)
    page = window.stack.widget(9)
    long_output = "第一行\n" + ("0123456789" * 400) + "\n最后一行"
    page._append_result(
        ScriptLineResult(
            12,
            "command",
            "adb shell dumpsys battery",
            True,
            long_output,
        )
    )
    shown = []
    monkeypatch.setattr(
        "adbtool.ui.pages.script_page.show_text",
        lambda parent, title, text: shown.append((parent, title, text)),
        raising=False,
    )

    for column in (0, 2, 3):
        page.table.cellDoubleClicked.emit(0, column)

    assert len(shown) == 3
    _parent, title, text = shown[0]
    assert title == "执行结果详情"
    assert "adb shell dumpsys battery" in text
    assert long_output in text


def test_script_buttons_fit_at_minimum_width(qtbot, tmp_path):
    window, _context = make_window(qtbot, tmp_path)
    window.resize(980, 640)
    window.show()
    window.nav.setCurrentRow(9)
    qtbot.wait(30)
    page = window.stack.widget(9)

    for button in page.findChildren(QPushButton):
        if button.isVisible():
            assert button.width() >= button.sizeHint().width(), button.text()
