from pathlib import Path

from adbtool.infrastructure.config import AppConfig, ConfigStore
from adbtool.infrastructure.execution_log import ExecutionLog, ExecutionRecord
from adbtool.services.adb import AdbService
from adbtool.services.devices import DeviceService
from adbtool.ui.context import AppContext
from adbtool.ui.main_window import MainWindow
from adbtool.ui.pages.log_page import LogPage
from adbtool.ui.status_bus import StatusBus


def make_window(qtbot, tmp_path, execution_log=None):
    config = AppConfig(adb_path=str(Path("platform-tools") / "adb.exe"))
    store = ConfigStore(tmp_path)
    adb = AdbService(Path(config.adb_path), execution_log=execution_log)
    devices = DeviceService(adb)
    context = AppContext(config, store, adb, devices, StatusBus())
    window = MainWindow(context, auto_refresh=False)
    qtbot.addWidget(window)
    return window, context


def make_record(ok: bool = True) -> ExecutionRecord:
    return ExecutionRecord(
        started_at="2026-11-13T21:00:00+08:00",
        serial="ABC",
        command="adb.exe -s ABC shell wm density",
        argv=("adb.exe", "-s", "ABC", "shell", "wm density"),
        ok=ok,
        exit_code=0 if ok else 1,
        duration_ms=42,
        stdout="Physical density: 450\nOverride density: 476",
        stderr="" if ok else "failure",
    )


def test_log_page_shows_records_and_detail(qtbot, tmp_path):
    window, context = make_window(qtbot, tmp_path)
    page = window.stack.widget(12)
    assert isinstance(page, LogPage)

    context.execution_log.add(make_record())

    assert page.table.rowCount() == 1
    assert page.table.item(0, 1).text() == "ABC"
    assert "wm density" in page.table.item(0, 2).text()

    page.table.selectRow(0)
    detail = page.detail.toPlainText()
    assert "adb.exe -s ABC shell wm density" in detail
    assert "Physical density: 450" in detail


def test_log_page_filters_failures(qtbot, tmp_path):
    window, context = make_window(qtbot, tmp_path)
    page = window.stack.widget(12)

    context.execution_log.add(make_record(ok=True))
    context.execution_log.add(make_record(ok=False))
    assert page.table.rowCount() == 2

    page.fail_only.setChecked(True)

    assert page.table.rowCount() == 1
    assert page.table.item(0, 3).text() == "失败"


def test_log_page_shows_only_current_run_and_keeps_history(qtbot, tmp_path):
    log_path = tmp_path / "execution-log.jsonl"
    log = ExecutionLog(log_path)
    log.add(make_record())
    window, context = make_window(qtbot, tmp_path, execution_log=log)
    page = window.stack.widget(12)

    assert page.table.rowCount() == 0
    assert "关闭后保留" in page.notice_label.text()
    assert page.open_folder_button.isEnabled() is True

    page.refresh_button.click()
    assert page.table.rowCount() == 0

    context.execution_log.add(make_record(ok=False))
    assert page.table.rowCount() == 1
    assert page.table.item(0, 3).text() == "失败"
    assert log_path.is_file()


def test_context_shutdown_flushes_execution_log(qtbot, tmp_path, monkeypatch):
    _window, context = make_window(qtbot, tmp_path)
    calls = []
    monkeypatch.setattr(context.execution_log, "flush", lambda: calls.append("flush"))

    context.shutdown()

    assert calls == ["flush"]


def test_open_folder_button_uses_directory_opener(qtbot, tmp_path, monkeypatch):
    import adbtool.ui.pages.log_page as log_page_module

    log_path = tmp_path / "logs" / "execution-log.jsonl"
    log = ExecutionLog(log_path)
    window, _context = make_window(qtbot, tmp_path, execution_log=log)
    page = window.stack.widget(12)
    opened = []
    monkeypatch.setattr(
        log_page_module,
        "open_folder",
        lambda folder: opened.append(folder) or True,
    )

    page.open_folder_button.click()

    assert opened == [log_path.parent]
    assert log_path.parent.is_dir()
