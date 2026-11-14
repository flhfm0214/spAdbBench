from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from adbtool.infrastructure.config import AppConfig, ConfigStore
from adbtool.infrastructure.parsers import DeviceInfo
from adbtool.services.adb import AdbService
from adbtool.services.devices import DeviceService
from adbtool.services.packages import PackageInfo
from adbtool.ui.context import AppContext
from adbtool.ui.main_window import MainWindow
from adbtool.ui.pages.apps_page import AppsPage
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


def test_apps_page_is_second_navigation_page(qtbot, tmp_path):
    window, _context = make_window(qtbot, tmp_path)
    assert isinstance(window.stack.widget(1), AppsPage)


def test_apps_page_filters_and_checkbox_selection(qtbot, tmp_path):
    window, _context = make_window(qtbot, tmp_path)
    page = window.stack.widget(1)
    page.show()

    page._packages = [
        PackageInfo("com.android.settings", enabled=True, system=True),
        PackageInfo("com.example.app", enabled=True, system=False),
        PackageInfo("com.google.android.gms", enabled=False, system=True),
    ]
    page._render_packages()

    assert page.table.rowCount() == 3
    page.search.setText("settings")
    assert page.table.rowCount() == 1

    page.search.clear()
    page.filter_combo.setCurrentIndex(page.filter_combo.findData("third"))
    assert page.table.rowCount() == 1
    assert page.table.item(0, 1).text() == "com.example.app"

    page.filter_combo.setCurrentIndex(page.filter_combo.findData("all"))
    page.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
    page._update_checked_count()
    assert page.checked_count_label.text().startswith("已选")


def _prepare_page(qtbot, tmp_path):
    window, _context = make_window(qtbot, tmp_path)
    page = window.stack.widget(1)
    window.show()
    window.nav.setCurrentRow(1)
    page._serial = "ABC"
    page._packages = [
        PackageInfo("com.example.one", enabled=True, system=False),
        PackageInfo("com.example.two", enabled=True, system=False),
        PackageInfo("com.example.three", enabled=False, system=False),
    ]
    page._render_packages()
    page.table.show()
    qtbot.wait(20)
    return window, page


def _click_cell(qtbot, page, row, column, modifier=Qt.KeyboardModifier.NoModifier):
    item = page.table.item(row, column)
    point = page.table.visualItemRect(item).center()
    if column == 0:
        point.setX(page.table.visualItemRect(item).left() + 10)
    QTest.mouseClick(page.table.viewport(), Qt.MouseButton.LeftButton, modifier, point)
    qtbot.wait(10)


def _double_click_cell(qtbot, page, row, column):
    item = page.table.item(row, column)
    point = page.table.visualItemRect(item).center()
    QTest.mouseDClick(
        page.table.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        point,
    )
    qtbot.wait(10)


def test_apps_page_disables_operations_without_checkboxes(qtbot, tmp_path):
    _window, page = _prepare_page(qtbot, tmp_path)

    _click_cell(qtbot, page, 0, 1)

    assert page.table.currentRow() == 0
    assert page._checked == set()
    assert all(not button.isEnabled() for button in page.action_buttons.values())
    assert page.batch_enable_button.isEnabled() is False
    assert page.batch_disable_button.isEnabled() is False
    assert page.google_enable_button.isEnabled() is True
    assert page.google_disable_button.isEnabled() is True


def test_apps_page_checks_with_checkbox_click_and_right_side_double_click(qtbot, tmp_path):
    _window, page = _prepare_page(qtbot, tmp_path)

    _click_cell(qtbot, page, 0, 0)
    _double_click_cell(qtbot, page, 2, 1)

    assert page._checked == {"com.example.one", "com.example.three"}
    assert page.action_buttons["launch"].isEnabled() is False
    assert page.batch_enable_button.isEnabled() is True


def test_apps_page_shift_click_checks_contiguous_range(qtbot, tmp_path):
    _window, page = _prepare_page(qtbot, tmp_path)

    _click_cell(qtbot, page, 0, 0)
    _click_cell(
        qtbot,
        page,
        2,
        0,
        Qt.KeyboardModifier.ShiftModifier,
    )

    assert page._checked == {
        "com.example.one",
        "com.example.two",
        "com.example.three",
    }
    assert page.checked_count_label.text() == "已选 3 个"


def test_apps_page_enables_extract_for_multiple_selected(qtbot, tmp_path):
    _window, page = _prepare_page(qtbot, tmp_path)

    _click_cell(qtbot, page, 0, 0)
    _click_cell(qtbot, page, 1, 0)

    assert page._checked == {"com.example.one", "com.example.two"}
    assert page.action_buttons["extract"].isEnabled() is True
    assert page.action_buttons["launch"].isEnabled() is False


def test_apps_page_extract_action_exports_checked_selection(qtbot, tmp_path, monkeypatch):
    _window, page = _prepare_page(qtbot, tmp_path)
    _click_cell(qtbot, page, 0, 0)
    _click_cell(qtbot, page, 1, 0)
    calls: list[bool] = []
    monkeypatch.setattr(page, "_export_selected", lambda: calls.append(True))

    page._run_single("extract")

    assert calls == [True]


def test_apps_page_activation_refreshes_packages_and_foreground(qtbot, tmp_path, monkeypatch):
    window, page = _prepare_page(qtbot, tmp_path)
    page._loaded_serial = "ABC"
    window.context.current_device = DeviceInfo(serial="ABC", state="device")
    calls: list[str] = []
    monkeypatch.setattr(page, "_refresh_packages", lambda: calls.append("packages"))
    monkeypatch.setattr(
        page.foreground_bar, "refresh", lambda: calls.append("foreground")
    )

    page.on_activated()

    assert calls == ["packages", "foreground"]
