from pathlib import Path

from PySide6.QtWidgets import QLabel

from adbtool.infrastructure.config import AppConfig, ConfigStore
from adbtool.services.adb import AdbService
from adbtool.services.devices import DeviceService
from adbtool.ui.context import AppContext
from adbtool.ui.main_window import MainWindow
from adbtool.ui.settings_dialog import SettingsDialog
from adbtool.ui.status_bus import StatusBus


def make_context(tmp_path):
    config = AppConfig(
        adb_path="",
        save_dir=str(tmp_path / "saved"),
        screenshot_dir=str(tmp_path / "saved" / "screenshots"),
        snapshot_dir=str(tmp_path / "saved" / "snapshots"),
    )
    store = ConfigStore(tmp_path)
    adb = AdbService(Path(config.adb_path or "adb"))
    devices = DeviceService(adb)
    status = StatusBus()
    return AppContext(config, store, adb, devices, status)


def test_device_detection_defaults_off_and_legacy_config_migrates():
    assert AppConfig().auto_refresh_devices is False
    legacy = AppConfig.from_dict({"auto_refresh_devices": True})
    assert legacy.auto_refresh_devices is False

    explicit = AppConfig.from_dict(
        {"auto_refresh_devices": True, "detection_settings_version": 2}
    )
    assert explicit.auto_refresh_devices is True


def test_settings_defaults_are_normalized():
    config = AppConfig.from_dict(
        {
            "preview_fps": 99,
            "scrcpy_max_size": 12,
            "scrcpy_bit_rate": 1,
            "auto_refresh_devices": "false",
            "metrics_interval_ms": 10,
        }
    )

    assert config.preview_fps == 60
    assert config.scrcpy_max_size == 320
    assert config.scrcpy_bit_rate == 500_000
    assert config.auto_refresh_devices is False
    assert config.metrics_interval_ms == 100


def test_settings_dialog_loads_current_values_and_saves(qtbot, tmp_path):
    context = make_context(tmp_path)
    dialog = SettingsDialog(context)
    qtbot.addWidget(dialog)

    assert dialog.preview_fps_spin.value() == context.config.preview_fps
    assert dialog.preview_fps_spin.maximum() == 60
    assert dialog.metrics_spin.maximum() == 60
    assert dialog.max_size_combo.itemData(dialog.max_size_combo.count() - 1) == 2160
    assert dialog.bitrate_combo.itemData(dialog.bitrate_combo.count() - 1) == 32_000_000
    labels = {label.text() for label in dialog.findChildren(QLabel)}
    assert "帧/秒（1–60）" in labels
    assert "秒（0.2–60）" in labels
    assert "秒（0.1–60；0 关闭）" in labels
    assert "上限 2160p" not in labels
    assert "上限 32 Mbps" not in labels
    assert dialog.save_dir_edit.text() == context.config.save_dir
    assert dialog.metrics_spin.value() == max(0, context.config.metrics_interval_ms // 1000)

    dialog.preview_fps_spin.setValue(4)
    dialog.metrics_spin.setValue(3)
    dialog.max_size_combo.setCurrentIndex(2)
    dialog.auto_refresh_check.setChecked(False)
    dialog.auto_preview_check.setChecked(False)
    dialog.save_dir_edit.setText(str(tmp_path / "output"))

    dialog.save()

    assert context.config.preview_fps == 4
    assert context.scrcpy.max_fps == 4
    assert context.config.metrics_interval_ms == 3000
    assert context.config.scrcpy_max_size == 1440
    assert context.config.auto_refresh_devices is False
    assert context.config.auto_start_preview is False
    assert context.config.save_dir == str(tmp_path / "output")
    assert context.config.screenshot_dir == str(tmp_path / "output" / "screenshots")
    assert context.config.snapshot_dir == str(tmp_path / "output" / "snapshots")

    loaded = context.config_store.load()
    assert loaded.preview_fps == 4
    assert loaded.save_dir == str(tmp_path / "output")


def test_settings_dialog_rejects_empty_save_dir(qtbot, tmp_path):
    context = make_context(tmp_path)
    dialog = SettingsDialog(context)
    qtbot.addWidget(dialog)
    dialog.save_dir_edit.setText("   ")

    seen = []
    from PySide6.QtWidgets import QMessageBox

    original = QMessageBox.warning
    QMessageBox.warning = staticmethod(lambda *args, **kwargs: seen.append(args[2]))
    try:
        dialog.save()
    finally:
        QMessageBox.warning = original

    assert seen and "不能为空" in seen[0]
    assert dialog.result() != dialog.DialogCode.Accepted


def test_main_window_has_bottom_settings_button(qtbot, tmp_path):
    context = make_context(tmp_path)
    window = MainWindow(context, auto_refresh=False)
    qtbot.addWidget(window)

    assert window.settings_button.text() == "设置"
    assert window.settings_button.parent() is not window.nav

    context.apply_config({"preview_fps": 5})
    assert context.config.preview_fps == 5
