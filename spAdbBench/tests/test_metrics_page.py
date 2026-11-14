from __future__ import annotations

from datetime import datetime
from pathlib import Path

from adbtool.infrastructure.config import AppConfig, ConfigStore
from adbtool.infrastructure.parsers import DeviceInfo
from adbtool.services.adb import AdbService
from adbtool.services.devices import DeviceService
from adbtool.services.metrics import CpuCore, CpuTimes, MetricsSample
from adbtool.ui.context import AppContext
from adbtool.ui.main_window import MainWindow
from adbtool.ui.pages.performance_page import PerformancePage
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


def make_sample(serial="ABC") -> MetricsSample:
    return MetricsSample(
        serial=serial,
        captured_at=datetime.now().astimezone(),
        cpu_usage=20,
        cores=(
            CpuCore(index=0, frequency_mhz=1800, usage_percent=15),
            CpuCore(index=1, frequency_mhz=2400, usage_percent=25),
        ),
        cpu_times=(
            CpuTimes(name="cpu", total=2000, idle=900),
            CpuTimes(name="cpu0", total=1000, idle=400),
            CpuTimes(name="cpu1", total=1000, idle=500),
        ),
        memory_total_kb=8_000_000,
        memory_available_kb=2_000_000,
        swap_total_kb=1_000_000,
        swap_free_kb=800_000,
        load_1=1.5,
        load_5=1.2,
        load_15=0.9,
        uptime_seconds=12345,
        battery_level=75,
        battery_status="充电中",
        battery_health="良好",
        battery_temperature_c=30.0,
        battery_voltage_mv=4200,
        battery_power="USB 供电",
        platform="sdm845",
        gpu_renderer="Adreno (TM) 640",
        gpu_vendor="Qualcomm",
        gles_version="OpenGL ES 3.2",
        model="Pixel 7",
    )


def test_performance_page_is_fifth_navigation_page(qtbot, tmp_path):
    window, _context = make_window(qtbot, tmp_path)

    assert isinstance(window.stack.widget(4), PerformancePage)
    assert window.metrics_panel is not None


def test_performance_page_renders_latest_sample(qtbot, tmp_path):
    _window, context = make_window(qtbot, tmp_path)
    page = PerformancePage(context)
    qtbot.addWidget(page)
    page.on_device_changed(DeviceInfo(serial="ABC", state="device"))

    page.render_sample(make_sample())

    assert page.cpu_value.text() == "20%"
    assert "2 核" in page.cpu_detail.text()
    assert page.cpu_table.rowCount() == 3
    assert page.cpu_table.item(1, 0).text() == "核心 0"
    assert page.cpu_table.item(1, 1).text() == "1800 MHz"
    assert page.cpu_table.item(1, 2).text() == "15%"
    assert "75%" in page.memory_value.text()
    assert "GB" in page.memory_detail.text()
    assert page.battery_value.text() == "75%"
    assert "充电中" in page.battery_detail.text()
    assert page.gpu_value.text() == "Adreno (TM) 640"
    assert "Qualcomm" in page.gpu_detail.text()
    assert "OpenGL ES 3.2" in page.gpu_detail.text()
    assert page.model_value.text() == "Pixel 7"
    assert page.platform_value.text() == "sdm845"
    assert page.load_value.text() == "1.50"
    assert "3 小时" in page.uptime_value.text()
    assert page.state_label.text().startswith("更新于")


def test_performance_page_changes_and_persists_interval(qtbot, tmp_path):
    _window, context = make_window(qtbot, tmp_path)
    page = PerformancePage(context)
    qtbot.addWidget(page)

    page.interval_combo.setValue(5.0)

    assert context.config.metrics_interval_ms == 5000
    assert context.metrics.interval_ms == 5000
    assert context.metrics._timer.interval() == 5000
    assert context.config_store.load().metrics_interval_ms == 5000

    page.interval_combo.setValue(0.1)
    assert context.config.metrics_interval_ms == 100
    assert context.metrics.interval_ms == 100

    page.interval_combo.setValue(0.0)
    assert context.config.metrics_interval_ms == 0
    assert context.metrics.interval_ms == 0
    assert context.metrics._timer.isActive() is False


def test_performance_page_clears_on_disconnect(qtbot, tmp_path):
    _window, context = make_window(qtbot, tmp_path)
    page = PerformancePage(context)
    qtbot.addWidget(page)
    page.on_device_changed(DeviceInfo(serial="ABC", state="device"))
    page.render_sample(make_sample())

    page.on_device_changed(None)

    assert page.cpu_value.text() == "—"
    assert page.cpu_table.rowCount() == 0
    assert page.interval_combo.isEnabled() is False


def test_performance_page_activation_refreshes_metrics_and_foreground(
    qtbot, tmp_path, monkeypatch
):
    _window, context = make_window(qtbot, tmp_path)
    page = PerformancePage(context)
    qtbot.addWidget(page)
    page._serial = "ABC"
    page._last_sample = make_sample()
    calls: list[str] = []
    monkeypatch.setattr(
        context.metrics, "refresh", lambda: calls.append("metrics")
    )
    monkeypatch.setattr(
        page.foreground_bar, "refresh", lambda: calls.append("foreground")
    )

    page.on_activated()

    assert calls == ["metrics", "foreground"]


def test_metrics_panel_renders_compact_values(qtbot, tmp_path):
    window, context = make_window(qtbot, tmp_path)
    panel = window.metrics_panel

    panel.update_sample(make_sample())

    assert panel.cpu_value.text() == "20%"
    assert "75%" in panel.memory_value.text()
    assert panel.battery_value.text() == "75%"
    assert "Adreno" in panel.gpu_value.text()
    assert "更新于" in panel.updated_label.text()


def test_main_window_starts_and_stops_monitoring_with_device(qtbot, tmp_path, monkeypatch):
    window, context = make_window(qtbot, tmp_path)
    calls = []
    monkeypatch.setattr(
        context.metrics,
        "set_device",
        lambda serial, interval_ms=None: calls.append(serial),
    )
    monkeypatch.setattr(window.stack.widget(0), "_load_props", lambda serial: None)

    window._select_device(DeviceInfo(serial="ABC", state="device"))
    window._select_device(DeviceInfo(serial="ABC", state="unauthorized"))

    assert calls == ["ABC", None]
