from __future__ import annotations

from datetime import datetime
from pathlib import Path

from adbtool.infrastructure.config import AppConfig, ConfigStore
from adbtool.services.adb import AdbService
from adbtool.services.devices import DeviceService
from adbtool.services.metrics import (
    CpuCore,
    CpuTimes,
    MetricsSample,
    SensorTemperature,
)
from adbtool.ui.context import AppContext
from adbtool.ui.control_window import ControlWindow
from adbtool.ui.status_bus import StatusBus


class FakeProcess:
    pass


def make_context(tmp_path) -> AppContext:
    config = AppConfig(adb_path=str(Path("adb.exe")))
    adb = AdbService(Path(config.adb_path))
    return AppContext(
        config,
        ConfigStore(tmp_path),
        adb,
        DeviceService(adb),
        StatusBus(),
    )


def test_control_window_restore_repositions_native_video(qtbot, tmp_path):
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication

    context = make_context(tmp_path)
    window = ControlWindow(context)
    qtbot.addWidget(window)
    window.show()
    calls: list[bool] = []
    window._restore_native = lambda: calls.append(True)

    QApplication.sendEvent(window, QEvent(QEvent.Type.WindowStateChange))
    qtbot.wait(20)

    assert calls == [True]


def make_sample() -> MetricsSample:
    return MetricsSample(
        serial="ABC",
        captured_at=datetime.now().astimezone(),
        cpu_usage=42,
        cores=(CpuCore(index=0, frequency_mhz=2100, usage_percent=42),),
        cpu_times=(CpuTimes(name="cpu", total=1000, idle=500),),
        memory_total_kb=8_000_000,
        memory_available_kb=2_000_000,
        battery_level=75,
        battery_temperature_c=31.5,
        gpu_frequency_mhz=587,
        sensor_temperatures=(
            SensorTemperature(name="cpu-0-0", celsius=48.2),
            SensorTemperature(name="gpu", celsius=45.0),
        ),
    )


def test_control_telemetry_shows_memory_frequency_and_temperatures(qtbot, tmp_path):
    context = make_context(tmp_path)
    window = ControlWindow(context)
    qtbot.addWidget(window)

    window.telemetry.update_sample(make_sample())

    assert window.telemetry.cpu_value.text() == "42%"
    assert window.telemetry.memory_value.text() == "75%"
    assert "GB" in window.telemetry.memory_detail.text()
    assert window.telemetry.cpu_frequency_value.text() == "2.10 GHz"
    assert window.telemetry.gpu_frequency_value.text() == "587 MHz"
    assert window.telemetry.cpu_temperature_value.text() == "48.2 ℃"
    assert window.telemetry.gpu_temperature_value.text() == "45.0 ℃"
    assert window.telemetry.battery_temperature_value.text() == "31.5 ℃"
    assert "cpu-0-0" in window.telemetry.sensor_detail.text()


def test_control_window_reuses_shared_metrics_monitor(qtbot, tmp_path):
    context = make_context(tmp_path)
    window = ControlWindow(context)
    qtbot.addWidget(window)

    assert window.monitor is context.metrics


def test_control_window_reflows_for_landscape(qtbot, tmp_path):
    from PySide6.QtWidgets import QBoxLayout

    context = make_context(tmp_path)
    window = ControlWindow(context)
    qtbot.addWidget(window)

    window._apply_orientation(True)
    qtbot.wait(10)

    assert window.body_layout.direction() == QBoxLayout.Direction.TopToBottom
    assert window.sidebar._landscape is True
    assert window.sidebar.minimumHeight() == window.sidebar.maximumHeight()
    assert window.sidebar.height() <= 360
    assert window.telemetry._compact is True

    window._apply_orientation(False)
    qtbot.wait(10)

    assert window.body_layout.direction() == QBoxLayout.Direction.LeftToRight
    assert window.sidebar.width() == 236
    assert window.telemetry._compact is False


def test_control_sampling_interval_is_editable(qtbot, tmp_path):
    context = make_context(tmp_path)
    window = ControlWindow(context)
    qtbot.addWidget(window)

    assert window.sidebar.interval_spin.value() == 1.0

    window.sidebar.interval_spin.setValue(0.1)

    assert context.config.metrics_interval_ms == 100
    assert window.monitor.interval_ms == 100


def test_unexpected_scrcpy_exit_keeps_control_window_open(qtbot, tmp_path):
    context = make_context(tmp_path)
    window = ControlWindow(context)
    qtbot.addWidget(window)
    window.show()

    window._on_finished(1)

    assert window.isVisible() is True
    assert window.sidebar.retry_button.isVisible() is True
    assert "退出码 1" in window.sidebar.status.text()
    window.close()


def test_retry_restarts_scrcpy_for_same_device(qtbot, tmp_path):
    context = make_context(tmp_path)
    calls: list[str] = []
    context.adb.shell = lambda *args, **kwargs: FakeProcess()
    window = ControlWindow(context)
    qtbot.addWidget(window)
    window._serial = "ABC"
    window.manager.start = lambda serial: calls.append(serial) or True
    window.monitor.set_device = lambda *args, **kwargs: None

    window._restart()

    assert calls == ["ABC"]
    assert window.sidebar.retry_button.isHidden() is True


def test_sidebar_contains_common_device_keys(qtbot, tmp_path):
    context = make_context(tmp_path)
    window = ControlWindow(context)
    qtbot.addWidget(window)

    assert list(window.sidebar.buttons) == [
        "主页",
        "返回",
        "任务",
        "音量 +",
        "音量 -",
        "电源",
        "菜单",
    ]


def test_sidebar_key_uses_adb_keyevent(qtbot, tmp_path):
    context = make_context(tmp_path)
    calls: list[tuple] = []
    context.adb.run = lambda *args, **kwargs: calls.append((args, kwargs)) or FakeProcess()
    window = ControlWindow(context)
    qtbot.addWidget(window)
    window._serial = "ABC"
    window.sidebar.set_enabled(True)

    window.sidebar.buttons["主页"].click()

    assert calls
    args, kwargs = calls[0]
    assert args == ("ABC", "shell", "input", "keyevent", "3")
    assert kwargs["timeout_ms"] == 5000
    assert kwargs["record"] is False
    assert "主页" in window.sidebar.status.text()
