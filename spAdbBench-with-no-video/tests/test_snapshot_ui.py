from pathlib import Path

from PySide6.QtCore import Qt

from adbtool.infrastructure.config import AppConfig, ConfigStore
from adbtool.infrastructure.parsers import DeviceInfo
from adbtool.services.adb import AdbService
from adbtool.services.devices import DeviceService
from adbtool.services.snapshot import CompareRow
from adbtool.services.snapshot_files import (
    DeviceSnapshot,
    SnapshotDocument,
    SnapshotItem,
    load_snapshot,
    save_snapshot,
)
from adbtool.ui.context import AppContext
from adbtool.ui.main_window import MainWindow
from adbtool.ui.pages.snapshot_page import SnapshotPage, default_snapshot_name
from adbtool.ui.status_bus import StatusBus


def make_context(tmp_path):
    config = AppConfig(
        adb_path=str(Path("platform-tools") / "adb.exe"),
        snapshot_dir=str(tmp_path / "snapshots"),
    )
    store = ConfigStore(tmp_path)
    adb = AdbService(Path(config.adb_path))
    devices = DeviceService(adb)
    return AppContext(config, store, adb, devices, StatusBus())


def make_page(qtbot, tmp_path, serial="ABC"):
    page = SnapshotPage(make_context(tmp_path))
    qtbot.addWidget(page)
    if serial:
        page.on_device_changed(DeviceInfo(serial=serial, state="device"))
    return page


def make_row(**overrides):
    data = {
        "key": "system.font_scale",
        "label": "字体倍率",
        "group": "显示与动画",
        "current": "1.0",
        "desired": "1.2",
        "available": True,
        "same": False,
        "read_command": "settings get system font_scale",
        "write_command": "settings put system font_scale {value}",
        "kind": "float",
    }
    data.update(overrides)
    return CompareRow(**data)


def make_snapshot(serial="ABC"):
    item = SnapshotItem(
        key="system.font_scale",
        label="字体倍率",
        group="显示与动画",
        value="1.2",
        read_command="settings get system font_scale",
        write_command="settings put system font_scale {value}",
        kind="float",
    )
    return DeviceSnapshot(
        serial=serial,
        model="Pixel 7",
        captured_at="2026-11-14T04:00:00+08:00",
        items={item.key: item},
    )


def test_compare_table_marks_unavailable(qtbot, tmp_path):
    page = make_page(qtbot, tmp_path)
    unavailable = make_row(
        key="display.size",
        label="分辨率",
        group="显示",
        current=None,
        desired="1080x2400",
        available=False,
        same=False,
        read_command="wm size",
        write_command="wm size {value}",
        kind="raw",
    )
    same = make_row(
        key="system.screen_off_timeout",
        label="自动锁屏",
        current="30000",
        desired="30000",
        same=True,
    )
    page.show_compare([make_row(), unavailable, same])

    assert page.table.item(1, 4).text() == "不可用"
    assert page.table.item(1, 0).checkState() == Qt.CheckState.Unchecked
    assert not page.table.item(1, 0).flags() & Qt.ItemFlag.ItemIsEnabled
    assert page.table.item(0, 0).checkState() == Qt.CheckState.Checked
    assert page.table.item(2, 0).checkState() == Qt.CheckState.Unchecked
    assert page.table.item(0, 4).text() == "不同"
    assert page.table.item(2, 4).text() == "一致"


def test_rollback_confirmation_lists_count(qtbot, tmp_path):
    page = make_page(qtbot, tmp_path)
    page.show_compare([make_row()])
    page.table.item(0, 0).setCheckState(Qt.CheckState.Checked)

    page.rollback_button.click()

    assert "1" in page.last_confirmation_text
    assert page.danger_dialog is not None
    assert page.danger_dialog.default_button.text() == "取消"
    page.danger_dialog.reject()


def test_unavailable_rows_are_skipped_by_rollback_selection(qtbot, tmp_path):
    page = make_page(qtbot, tmp_path)
    unavailable = make_row(
        key="display.size",
        label="分辨率",
        current=None,
        desired="1080x2400",
        available=False,
        read_command="wm size",
        write_command="wm size {value}",
    )
    page.show_compare([make_row(), unavailable])
    page.table.item(1, 0).setCheckState(Qt.CheckState.Checked)

    selected = page._selected_rows()

    assert [row.key for row in selected] == ["system.font_scale"]


def test_capture_result_writes_mergeable_document(qtbot, tmp_path):
    page = make_page(qtbot, tmp_path)
    target = page.snapshot_dir() / "manual-snapshot.json"
    page.ask_save_path = lambda default_path: str(target)

    page._apply_capture_result(make_snapshot("ABC"))

    assert target.exists()
    document = load_snapshot(target)
    assert document.devices["ABC"].model == "Pixel 7"
    assert page.snapshot_list.rowCount() == 1
    assert page.last_saved_path == target

    page.ask_save_path = lambda default_path: str(target)
    page._apply_capture_result(make_snapshot("XYZ"))

    document = load_snapshot(target)
    assert set(document.devices) == {"ABC", "XYZ"}


def test_import_reports_device_missing_from_snapshot(qtbot, tmp_path):
    page = make_page(qtbot, tmp_path, serial="ABC")
    source = tmp_path / "other-device.json"
    save_snapshot(
        SnapshotDocument(devices={"XYZ": make_snapshot("XYZ")}),
        source,
    )
    page.ask_open_path = lambda: str(source)

    page._import_snapshot()

    assert "当前设备不在快照中" in page.message_label.text()
    assert page.rollback_button.isEnabled() is False


def test_default_snapshot_name_contains_serial_and_timestamp():
    name = default_snapshot_name("ABC:123")

    assert name.startswith("adbtool-snapshot-ABC_123-")
    assert name.endswith(".json")
    assert ":" not in name


def test_main_window_embeds_snapshot_page(qtbot, tmp_path):
    context = make_context(tmp_path)
    window = MainWindow(context, auto_refresh=False)
    qtbot.addWidget(window)

    assert isinstance(window.stack.widget(11), SnapshotPage)
    assert window.nav.item(11).text() == "配置快照"
    window.close()
