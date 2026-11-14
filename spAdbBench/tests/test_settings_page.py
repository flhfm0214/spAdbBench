from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QPushButton

from adbtool.infrastructure.config import AppConfig, ConfigStore
from adbtool.infrastructure.parsers import DeviceInfo
from adbtool.services.adb import AdbService
from adbtool.services.devices import DeviceService
from adbtool.services.settings import SettingsService
from adbtool.ui.context import AppContext
from adbtool.ui.main_window import MainWindow
from adbtool.ui.pages.settings_page import SettingsPage
from adbtool.ui.status_bus import StatusBus
from tests.test_settings_service import FakeAdb


def make_window(qtbot, tmp_path):
    config = AppConfig(adb_path=str(Path("platform-tools") / "adb.exe"))
    store = ConfigStore(tmp_path)
    adb = AdbService(Path(config.adb_path))
    devices = DeviceService(adb)
    context = AppContext(config, store, adb, devices, StatusBus())
    window = MainWindow(context, auto_refresh=False)
    qtbot.addWidget(window)
    return window, context


def prepare_page(page: SettingsPage, tmp_path):
    fake = FakeAdb()
    page.service = SettingsService(fake, page.context.settings_history)
    page._serial = "ABC"
    page._update_controls()
    return fake


def test_settings_page_is_sixth_navigation_page(qtbot, tmp_path):
    window, _context = make_window(qtbot, tmp_path)

    assert isinstance(window.stack.widget(6), SettingsPage)
    assert window.nav.count() == 13


def test_font_apply_waits_for_confirmation(qtbot, tmp_path, monkeypatch):
    window, _context = make_window(qtbot, tmp_path)
    page = window.stack.widget(6)
    fake = prepare_page(page, tmp_path)
    specs = []

    monkeypatch.setattr(page, "_confirm", lambda spec: specs.append(spec) or False)
    page.font_scale.setValue(1.15)
    page.apply_font.click()

    assert specs[-1].key == "settings.font_scale"
    assert fake.shells == []

    monkeypatch.setattr(page, "_confirm", lambda _spec: True)
    page.apply_font.click()

    assert fake.shells
    assert fake.shells[0][1] == "settings put system font_scale '1.15'"


def test_timeout_ui_accepts_zero_and_upper_limit(qtbot, tmp_path, monkeypatch):
    window, _context = make_window(qtbot, tmp_path)
    page = window.stack.widget(6)
    fake = prepare_page(page, tmp_path)
    monkeypatch.setattr(page, "_confirm", lambda _spec: True)

    assert page.timeout_spin.minimum() == 0
    assert page.timeout_spin.maximum() == 65535
    assert page.timeout_spin.specialValueText() == "不熄屏"
    assert page.timeout_slider.maximum() == 1000

    page.timeout_spin.setValue(0)
    page.apply_timeout.click()
    assert fake.shells[-1][1] == "settings put system screen_off_timeout '0'"

    page.timeout_spin.setValue(65535)
    page.apply_timeout.click()
    assert fake.shells[-1][1] == "settings put system screen_off_timeout '65535000'"


def test_settings_sliders_sync_with_number_fields(qtbot, tmp_path):
    window, _context = make_window(qtbot, tmp_path)
    page = window.stack.widget(6)

    assert 300 < page.font_slider.value() < 400
    page.font_scale.setValue(1.5)
    assert 500 < page.font_slider.value() < 600

    page.font_slider.setValue(1000)
    assert page.font_scale.value() == 3.0

    key = next(iter(page.animation_spins))
    page.animation_spins[key].setValue(7.0)
    assert page.animation_sliders[key].value() > 800

    page.animation_sliders[key].setValue(1000)
    assert page.animation_spins[key].value() == 10.0

    assert 300 < page.timeout_slider.value() < 400
    page.timeout_slider.setValue(1000)
    assert page.timeout_spin.value() == 65535


def test_hidden_setting_write_updates_history_after_success(qtbot, tmp_path, monkeypatch):
    window, context = make_window(qtbot, tmp_path)
    page = window.stack.widget(6)
    fake = prepare_page(page, tmp_path)
    monkeypatch.setattr(page, "_confirm", lambda _spec: True)

    page.hidden_table.setCurrentIndex(page.hidden_table.findData("secure"))
    page.hidden_key.setText("icon_blacklist")
    page.hidden_value.setText("clock,alarm")
    page.write_hidden.click()

    process = fake.shells[-1][2]
    assert "settings put secure icon_blacklist 'clock,alarm'" == fake.shells[-1][1]
    assert context.settings_history.entries("ABC") == []

    process.complete()

    entries = context.settings_history.entries("ABC")
    assert len(entries) == 1
    assert entries[0].value == "clock,alarm"
    assert page.history_table.rowCount() == 1


def test_hidden_write_rejects_empty_key(qtbot, tmp_path):
    window, _context = make_window(qtbot, tmp_path)
    page = window.stack.widget(6)
    fake = prepare_page(page, tmp_path)

    page.hidden_key.clear()
    page.hidden_value.setText("value")
    page.write_hidden.click()

    assert fake.shells == []
    assert "键" in page.message_label.text()


def test_icon_blacklist_checkboxes_and_select_all(qtbot, tmp_path):
    window, _context = make_window(qtbot, tmp_path)
    page = window.stack.widget(6)
    prepare_page(page, tmp_path)

    assert len(page.icon_checks) >= 10
    assert all(check.isChecked() is False for check in page.icon_checks.values())

    page.all_icons_button.click()
    assert all(check.isChecked() is True for check in page.icon_checks.values())

    page.clear_icons_button.click()
    assert all(check.isChecked() is False for check in page.icon_checks.values())


def test_icon_blacklist_preserves_unknown_vendor_icons(qtbot, tmp_path, monkeypatch):
    window, _context = make_window(qtbot, tmp_path)
    page = window.stack.widget(6)
    fake = prepare_page(page, tmp_path)
    page._apply_read_value("icons", "icon_blacklist", "rotate,nfc,clock")
    monkeypatch.setattr(page, "_confirm", lambda _spec: True)

    assert page.icon_checks["clock"].isChecked() is True
    assert page.icon_checks["rotate"].isChecked() is True
    assert "nfc" in page.other_icons_label.text()

    page.apply_icons.click()

    assert "settings put secure icon_blacklist" in fake.shells[-1][1]
    assert "nfc" in fake.shells[-1][1]
    assert "clock" in fake.shells[-1][1]


def test_icon_text_explicitly_says_hide_status_bar_icons(qtbot, tmp_path):
    window, _context = make_window(qtbot, tmp_path)
    page = window.stack.widget(6)

    assert "隐藏状态栏" in page.icons_group.title()
    assert "隐藏状态栏" in page.icons_note.text()
    assert "勾选" in page.icons_note.text()


def test_settings_buttons_fit_at_minimum_width(qtbot, tmp_path):
    window, _context = make_window(qtbot, tmp_path)
    window.resize(980, 640)
    window.show()
    window.nav.setCurrentRow(6)
    qtbot.wait(30)
    page = window.stack.widget(6)

    buttons = page.findChildren(QPushButton)
    for button in buttons:
        if button.isVisible():
            assert button.width() >= button.sizeHint().width(), button.text()
