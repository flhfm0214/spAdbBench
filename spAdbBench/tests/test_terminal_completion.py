from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, Qt, Signal
from PySide6.QtWidgets import QLineEdit, QPushButton

from adbtool.infrastructure.config import AppConfig, ConfigStore
from adbtool.infrastructure.process import ProcessResult
from adbtool.services.adb import AdbService
from adbtool.services.completion_config import ensure_completion_dir
from adbtool.services.devices import DeviceService
from adbtool.services.terminal import (
    CompletionCatalog,
    TerminalSession,
    command_specs,
    strip_ansi,
)
from adbtool.ui.context import AppContext
from adbtool.ui.main_window import MainWindow
from adbtool.ui.pages.terminal_page import TerminalPage
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


def shown_page(qtbot, tmp_path):
    window, _context = make_window(qtbot, tmp_path)
    window.show()
    window.nav.setCurrentRow(10)
    qtbot.wait(20)
    page = window.stack.widget(10)
    page._serial = "ABC"
    page.session = FakeSession()
    page.terminal.set_editable(True)
    page.input.setEnabled(True)
    page._update_controls()
    return window, page


def use_shell_mode(page) -> None:
    page._mode = "shell"
    page.terminal.set_prompt("shell> ")
    page.session = FakeSession()
    page.terminal.set_editable(True)
    page._update_controls()


def test_candidates_are_layered():
    catalog = CompletionCatalog()
    catalog.set_packages(["com.example.app", "com.android.settings"])

    assert "shell" in catalog.candidates("sh")
    assert "pm" in catalog.candidates("p")
    assert "com.example.app" in catalog.candidates("com.ex")


def test_candidate_prefix_is_case_sensitive_for_packages():
    catalog = CompletionCatalog(packages=["com.Example"])

    assert "com.Example" in catalog.candidates("com.Ex")
    assert "com.Example" not in catalog.candidates("com.ex")


def test_strip_ansi_keeps_unicode_text():
    assert strip_ansi("\x1b[31m错误\x1b[0m\r\n完成") == "错误\n完成"


def test_terminal_page_is_tenth_navigation_page(qtbot, tmp_path):
    window, _context = make_window(qtbot, tmp_path)

    assert isinstance(window.stack.widget(10), TerminalPage)
    assert window.nav.count() == 13


def test_input_lives_inside_terminal_frame(qtbot, tmp_path):
    _window, page = shown_page(qtbot, tmp_path)

    assert page.terminal_frame.isAncestorOf(page.output)
    assert page.terminal_frame.isAncestorOf(page.input)


def test_command_reference_lists_all_commands_with_syntax(qtbot, tmp_path):
    _window, page = shown_page(qtbot, tmp_path)
    specs = command_specs()

    assert page.command_table.rowCount() == len(specs)
    assert page.command_table.columnCount() == 4
    for row in range(page.command_table.rowCount()):
        assert page.command_table.item(row, 1).text()
        assert page.command_table.item(row, 2).text()
        assert page.command_table.item(row, 3).text()


def test_command_reference_search_filters_rows(qtbot, tmp_path):
    _window, page = shown_page(qtbot, tmp_path)
    page.command_search.setText("dumpsys")

    visible = [
        row
        for row in range(page.command_table.rowCount())
        if not page.command_table.isRowHidden(row)
    ]
    assert visible
    assert all(
        "dumpsys" in page.command_table.item(row, 1).text().lower()
        or "dumpsys" in page.command_table.item(row, 2).text().lower()
        or "dumpsys" in page.command_table.item(row, 3).text().lower()
        for row in visible
    )


def test_command_reference_shows_full_syntax_on_selection(qtbot, tmp_path):
    _window, page = shown_page(qtbot, tmp_path)
    row = next(
        row
        for row in range(page.command_table.rowCount())
        if page.command_table.item(row, 1).text() == "dumpsys"
        and page.command_table.item(row, 0).text() == "shell"
    )

    page.command_table.selectRow(row)

    assert "dumpsys <服务名> [参数]" in page.command_detail.text()


def test_command_reference_double_click_fills_input(qtbot, tmp_path):
    _window, page = shown_page(qtbot, tmp_path)
    row = next(
        row
        for row in range(page.command_table.rowCount())
        if page.command_table.item(row, 1).text() == "dumpsys"
        and page.command_table.item(row, 0).text() == "shell"
    )

    page.command_table.cellDoubleClicked.emit(row, 1)

    assert page.input.text() == "dumpsys "
    assert page.input.hasFocus()


def test_tab_on_empty_input_lists_first_twenty_commands(qtbot, tmp_path):
    _window, page = shown_page(qtbot, tmp_path)
    page.input.clear()
    page.input.setFocus()

    qtbot.keyClick(page.input, Qt.Key_Tab)

    assert "候选（20）" in page.output.toPlainText()
    assert page.input.text() == ""
    assert page.input.hasFocus()


def test_tab_with_unique_candidate_completes_and_adds_space(qtbot, tmp_path):
    _window, page = shown_page(qtbot, tmp_path)
    page.input.setText("devic")

    qtbot.keyClick(page.input, Qt.Key_Tab)

    assert page.input.text() == "devices "
    assert "候选" not in page.output.toPlainText()


def test_shell_mode_does_not_offer_local_adb_commands(qtbot, tmp_path):
    _window, page = shown_page(qtbot, tmp_path)
    use_shell_mode(page)
    page.input.setText("pu")
    page.input.setFocus()

    qtbot.keyClick(page.input, Qt.Key_Tab)

    assert page.input.text() == "pu"
    assert "push" not in page.output.toPlainText()
    assert page.input.hasFocus()


def test_tab_with_multiple_candidates_lists_them_on_new_lines(qtbot, tmp_path):
    _window, page = shown_page(qtbot, tmp_path)
    page.input.setText("p")
    page.input.setFocus()

    qtbot.keyClick(page.input, Qt.Key_Tab)

    text = page.output.toPlainText()
    assert "\n候选（" in text
    assert "\n  push" in text
    assert page.input.text() == "p"
    assert page.input.hasFocus()


def test_shell_mode_lists_shell_candidates(qtbot, tmp_path):
    _window, page = shown_page(qtbot, tmp_path)
    use_shell_mode(page)
    page.input.setText("p")
    page.input.setFocus()

    qtbot.keyClick(page.input, Qt.Key_Tab)

    text = page.output.toPlainText()
    assert "\n  pm" in text
    assert "\n  push" not in text


def test_tab_completes_package_argument(qtbot, tmp_path):
    _window, page = shown_page(qtbot, tmp_path)
    use_shell_mode(page)
    page.catalog.set_packages(["com.example.app"])
    page.input.setText("pm list packages com.ex")
    page.input.setFocus()

    qtbot.keyClick(page.input, Qt.Key_Tab)

    assert page.input.text() == "pm list packages com.example.app "


def test_tab_completes_command_after_pipe(qtbot, tmp_path):
    _window, page = shown_page(qtbot, tmp_path)
    use_shell_mode(page)
    page.input.setText("echo hello | gr")
    page.input.setFocus()

    qtbot.keyClick(page.input, Qt.Key_Tab)

    assert page.input.text() == "echo hello | grep "


def test_tab_after_pipe_lists_commands_without_touching_pipeline(qtbot, tmp_path):
    _window, page = shown_page(qtbot, tmp_path)
    use_shell_mode(page)
    page.input.setText("echo hello |")
    page.input.setFocus()

    qtbot.keyClick(page.input, Qt.Key_Tab)

    text = page.output.toPlainText()
    assert page.input.text() == "echo hello |"
    assert "候选（" in text
    assert "\n  sort" in text
    assert "\n  uniq" in text
    assert "\n  xargs" in text


def test_existing_completion_file_gets_new_pipeline_defaults(tmp_path):
    directory = ensure_completion_dir(tmp_path)
    data_file = directory / "commands.json"
    data = json.loads(data_file.read_text(encoding="utf-8"))
    data["commands"].pop("sort", None)
    data["commands"]["my-command"] = {"description": "自定义命令"}
    data_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    ensure_completion_dir(tmp_path)

    updated = json.loads(data_file.read_text(encoding="utf-8"))
    assert "sort" in updated["commands"]
    assert updated["commands"]["my-command"]["description"] == "自定义命令"


def test_pipe_catalogue_includes_common_linux_filters(qtbot, tmp_path):
    _window, page = shown_page(qtbot, tmp_path)
    use_shell_mode(page)

    commands = page.catalog.pipe_commands()

    for name in (
        "grep",
        "awk",
        "sed",
        "cut",
        "sort",
        "uniq",
        "tr",
        "tee",
        "head",
        "tail",
        "wc",
        "xargs",
        "paste",
        "join",
        "comm",
        "od",
        "hexdump",
        "strings",
        "base64",
        "md5sum",
        "gzip",
        "tar",
    ):
        assert name in commands


def test_tab_completes_pipeline_filter_and_its_options(qtbot, tmp_path):
    _window, page = shown_page(qtbot, tmp_path)
    use_shell_mode(page)
    page.input.setText("cat /sdcard/a.txt | sor")
    page.input.setFocus()

    qtbot.keyClick(page.input, Qt.Key_Tab)
    assert page.input.text() == "cat /sdcard/a.txt | sort "

    page.input.setText("cat /sdcard/a.txt | sort -")
    page.input.setFocus()
    qtbot.keyClick(page.input, Qt.Key_Tab)
    text = page.output.toPlainText()
    assert "  -n" in text
    assert "  -r" in text


def test_shell_mode_completes_new_pipeline_command_at_line_start(qtbot, tmp_path):
    _window, page = shown_page(qtbot, tmp_path)
    use_shell_mode(page)
    page.input.setText("uni")
    page.input.setFocus()

    qtbot.keyClick(page.input, Qt.Key_Tab)

    assert "uniq" in page.output.toPlainText()


def test_pipe_inside_quotes_is_not_a_completion_boundary(qtbot, tmp_path):
    _window, page = shown_page(qtbot, tmp_path)
    use_shell_mode(page)
    page.input.setText("echo 'a|b' | gr")
    page.input.setFocus()

    qtbot.keyClick(page.input, Qt.Key_Tab)

    assert page.input.text() == "echo 'a|b' | grep "


def test_tab_without_candidate_keeps_command_and_focus(qtbot, tmp_path):
    _window, page = shown_page(qtbot, tmp_path)
    other = QLineEdit(page)
    other.show()
    page.input.setTabOrder(page.input, other)
    command = "cat /sdcard/中文 文件.txt"
    page.input.setText(command)
    page.input.setFocus()

    qtbot.keyClick(page.input, Qt.Key_Tab)

    assert page.input.text() == command
    assert page.input.hasFocus()
    assert other.hasFocus() is False
    assert "候选" not in page.output.toPlainText()


class FakeSession(QObject):
    output = Signal(str)
    state = Signal(str)
    error = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.running = True
        self.sent: list[str] = []
        self.started: list[str] = []
        self.interrupts = 0

    def start(self, serial: str) -> None:
        self.started.append(serial)
        self.running = True

    def send(self, text: str) -> None:
        self.sent.append(text)

    def interrupt(self) -> None:
        self.interrupts += 1

    def stop(self) -> None:
        self.running = False

    def wait(self, _timeout=1500) -> None:
        pass


class FakeAdbSession(QObject):
    output = Signal(str)
    state = Signal(str)
    error = Signal(str)
    finished = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.running = False
        self.started: list[tuple[str, str]] = []

    def start(self, serial: str, command: str) -> None:
        self.started.append((serial, command))
        self.running = True

    def stop(self) -> None:
        self.running = False

    def interrupt(self) -> None:
        self.running = False

    def wait(self, _timeout=1500) -> None:
        pass


def test_default_mode_is_adb_and_can_switch_to_shell(qtbot, tmp_path):
    _window, page = shown_page(qtbot, tmp_path)
    page.mode_combo.setCurrentIndex(0)

    assert page.mode == "adb"
    assert page.terminal.prompt == "adb> "
    assert page.reconnect_button.isVisible() is False

    page.mode_combo.setCurrentIndex(1)

    assert page.mode == "shell"
    assert page.terminal.prompt == "shell> "
    assert page.reconnect_button.isVisible() is True
    assert page.session.started == ["ABC"]


def test_adb_mode_submits_to_adb_session(qtbot, tmp_path):
    _window, page = shown_page(qtbot, tmp_path)
    adb = FakeAdbSession()
    page.adb_session = adb
    page.input.setText("devices")
    page.input.setFocus()

    qtbot.keyClick(page.input, Qt.Key_Return)

    assert adb.started == [("ABC", "devices")]
    assert page.output.toPlainText() == "adb> devices\nadb> "


def test_page_echoes_command_and_navigates_history(qtbot, tmp_path):
    _window, page = shown_page(qtbot, tmp_path)
    use_shell_mode(page)
    session = FakeSession()
    page.session = session
    session.output.connect(page._append_output)
    session.state.connect(page._on_shell_state)
    session.error.connect(page._on_session_error)
    page.input.setEnabled(True)
    page.terminal.set_editable(True)
    page.input.setText("echo 你好")
    page.input.setFocus()

    qtbot.keyClick(page.input, Qt.Key_Return)

    assert session.sent == ["echo 你好"]
    assert "shell> echo 你好\nshell> " in page.output.toPlainText()
    assert page.input.text() == ""

    qtbot.keyClick(page.input, Qt.Key_Up)
    assert page.input.text() == "echo 你好"
    qtbot.keyClick(page.input, Qt.Key_Down)
    assert page.input.text() == ""


class FakePackageProcess(QObject):
    finished = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.is_running = True
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True
        self.is_running = False

    def wait(self, _timeout=1500) -> None:
        pass


class FakePackageService:
    def __init__(self) -> None:
        self.processes: list[FakePackageProcess] = []

    def list_packages(self, _serial: str) -> FakePackageProcess:
        process = FakePackageProcess()
        self.processes.append(process)
        return process


def package_output(*packages: str) -> str:
    lines = ["__ADBTOOL_ALL__"]
    lines.extend(f"package:{package}" for package in packages)
    lines.extend(["__ADBTOOL_DISABLED__", "__ADBTOOL_SYSTEM__", "__ADBTOOL_END__"])
    return "\n".join(lines)


def test_package_names_load_asynchronously(qtbot, tmp_path):
    _window, page = shown_page(qtbot, tmp_path)
    service = FakePackageService()
    page.package_service = service
    page._serial = "ABC"

    page._load_packages()
    process = service.processes[0]
    process.finished.emit(
        ProcessResult(
            ok=True,
            exit_code=0,
            stdout=package_output("com.example.app"),
            stderr="",
        )
    )

    assert "com.example.app" in page.catalog.candidates("com.ex")


def test_old_package_load_is_discarded_after_device_switch(qtbot, tmp_path):
    _window, page = shown_page(qtbot, tmp_path)
    service = FakePackageService()
    page.package_service = service
    page._serial = "A"
    page._load_packages()
    old = service.processes[0]

    page._serial = "B"
    page._load_packages()
    new = service.processes[1]
    old.finished.emit(
        ProcessResult(
            ok=True,
            exit_code=0,
            stdout=package_output("com.old.app"),
            stderr="",
        )
    )

    assert "com.old.app" not in page.catalog.candidates("com.")
    new.finished.emit(
        ProcessResult(
            ok=True,
            exit_code=0,
            stdout=package_output("com.new.app"),
            stderr="",
        )
    )
    assert "com.new.app" in page.catalog.candidates("com.")


FAKE_SHELL = """
import sys
sys.stdout.buffer.write("READY\\n".encode("utf-8"))
sys.stdout.flush()
for line in sys.stdin.buffer:
    sys.stdout.buffer.write(b"ECHO:" + line)
    sys.stdout.flush()
"""


def test_terminal_session_streams_utf8_and_preserves_spaces(qtbot, monkeypatch):
    class FakeAdb:
        adb_path = Path("adb.exe")

    session = TerminalSession(FakeAdb())
    monkeypatch.setattr(
        session,
        "_build_argv",
        lambda _serial: [sys.executable, "-u", "-c", FAKE_SHELL],
    )
    chunks: list[str] = []
    session.output.connect(chunks.append)
    session.start("ABC")
    qtbot.waitUntil(lambda: "READY" in "".join(chunks), timeout=5000)

    session.send("echo 中文 C:\\Program Files\\adb.exe")

    expected = "ECHO:echo 中文 C:\\Program Files\\adb.exe"
    qtbot.waitUntil(lambda: expected in "".join(chunks), timeout=5000)
    session.stop()
    qtbot.waitUntil(lambda: not session.running, timeout=5000)


def test_shutdown_stops_and_waits_for_session(qtbot, tmp_path):
    _window, page = shown_page(qtbot, tmp_path)
    calls = []
    session = FakeSession()
    session.stop = lambda: calls.append("stop")
    session.wait = lambda timeout=1500: calls.append(("wait", timeout))
    page.session = session

    page.shutdown()

    assert calls[0] == "stop"
    assert calls[1] == ("wait", 1500)


def test_command_panel_is_not_clipped_at_minimum_size(qtbot, tmp_path):
    window, _context = make_window(qtbot, tmp_path)
    window.resize(980, 640)
    window.show()
    window.nav.setCurrentRow(10)
    qtbot.wait(50)

    page = window.stack.widget(10)
    table_bottom = page.command_table.mapTo(
        window, QPoint(0, page.command_table.height())
    ).y()
    assert table_bottom <= window.statusBar().geometry().top()
    assert page.command_table.height() >= 60
    assert page.terminal_frame.height() >= 120


def test_terminal_buttons_fit_at_minimum_width(qtbot, tmp_path):
    window, _context = make_window(qtbot, tmp_path)
    window.resize(980, 640)
    window.show()
    window.nav.setCurrentRow(10)
    qtbot.wait(30)
    page = window.stack.widget(10)

    for button in page.findChildren(QPushButton):
        if button.isVisible():
            assert button.width() >= button.sizeHint().width(), button.text()
