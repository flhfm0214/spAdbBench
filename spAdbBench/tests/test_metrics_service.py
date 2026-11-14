from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from adbtool.infrastructure.process import ProcessResult
from adbtool.services.metrics import (
    MetricsMonitor,
    build_metrics_script,
    parse_metrics_sample,
)


SAMPLE_ONE = """__STAT__
cpu  1000 100 500 8000 100 20 30 0 0 0
cpu0 600 50 300 4000 50 10 20 0 0 0
cpu1 400 50 200 4000 50 10 10 0 0 0
intr 12345 0 0
__FREQ__
/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq 1800000
/sys/devices/system/cpu/cpu1/cpufreq/scaling_cur_freq 2400000
__GPUFREQ__
/sys/class/kgsl/kgsl-3d0/gpuclk 587000000
/sys/class/devfreq/5000000.qcom,kgsl-3d0/cur_freq 587000
__THERMAL__
cpu-0-0|48000
cpu-1-0|50000
gpu|45000
battery|32000
skin|30000
__ROTATION__
SurfaceOrientation: 1
__MEM__
MemTotal:        8000000 kB
MemFree:          200000 kB
MemAvailable:    2000000 kB
Buffers:           10000 kB
Cached:           500000 kB
SwapTotal:       1000000 kB
SwapFree:         800000 kB
__BATTERY__
Current Battery Service state:
  AC powered: false
  USB powered: true
  Wireless powered: false
  status: 2
  health: 2
  level: 75
  voltage: 4200
  temperature: 300
  technology: Li-ion
__LOAD__
1.50 1.20 0.90 2/500 1234
__UPTIME__
12345.67 9000.00
__GLES__
GLES: Qualcomm, Adreno (TM) 640, OpenGL ES 3.2 V@0502.0
__PLATFORM__
sdm845
__MODEL__
Pixel 7
__EGL__
adreno
__GLVER__
196610
"""

SAMPLE_TWO = """__STAT__
cpu  1200 100 500 8800 100 20 30 0 0 0
cpu0 700 50 300 4400 50 10 20 0 0 0
cpu1 500 50 200 4400 50 10 10 0 0 0
__FREQ__
/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq 2000000
/sys/devices/system/cpu/cpu1/cpufreq/scaling_cur_freq 2600000
__MEM__
MemTotal:        8000000 kB
MemAvailable:    2400000 kB
SwapTotal:       1000000 kB
SwapFree:        1000000 kB
__BATTERY__
  AC powered: true
  USB powered: false
  Wireless powered: false
  status: 5
  health: 2
  level: 100
  voltage: 4300
  temperature: 310
__LOAD__
0.50 0.80 1.00 1/500 1234
__UPTIME__
12355.67 9000.00
"""


def test_parse_metrics_sample_reads_cpu_memory_battery_and_gpu():
    sample = parse_metrics_sample(SAMPLE_ONE, "ABC")

    assert sample.serial == "ABC"
    assert sample.cpu_usage is None
    assert len(sample.cores) == 2
    assert [core.index for core in sample.cores] == [0, 1]
    assert [core.frequency_mhz for core in sample.cores] == [1800, 2400]
    assert sample.average_frequency_mhz == 2100
    assert sample.memory_total_kb == 8000000
    assert sample.memory_available_kb == 2000000
    assert sample.memory_used_kb == 6000000
    assert sample.memory_percent == 75
    assert sample.swap_total_kb == 1000000
    assert sample.swap_free_kb == 800000
    assert sample.battery_level == 75
    assert sample.battery_status == "充电中"
    assert sample.battery_health == "良好"
    assert sample.battery_temperature_c == 30.0
    assert sample.battery_voltage_mv == 4200
    assert sample.battery_power == "USB 供电"
    assert sample.load_1 == 1.5
    assert sample.load_5 == 1.2
    assert sample.load_15 == 0.9
    assert sample.uptime_seconds == 12345
    assert sample.platform == "sdm845"
    assert sample.model == "Pixel 7"
    assert sample.gpu_renderer == "Adreno (TM) 640"
    assert sample.gpu_vendor == "Qualcomm"
    assert sample.gles_version == "OpenGL ES 3.2"
    assert sample.gpu_frequency_mhz == 587
    assert sample.cpu_temperature_c == 48.0
    assert sample.gpu_temperature_c == 45.0
    assert sample.display_rotation == 1
    assert [(item.name, item.celsius) for item in sample.sensor_temperatures] == [
        ("battery", 32.0),
        ("cpu-0-0", 48.0),
        ("cpu-1-0", 50.0),
        ("gpu", 45.0),
        ("skin", 30.0),
    ]
    assert sample.has_data is True


def test_parse_metrics_sample_computes_cpu_delta():
    first = parse_metrics_sample(SAMPLE_ONE, "ABC")
    second = parse_metrics_sample(SAMPLE_TWO, "ABC", previous=first.cpu_times)

    assert second.cpu_usage == 20
    assert [core.usage_percent for core in second.cores] == [20, 20]
    assert second.average_frequency_mhz == 2300
    assert second.memory_percent == 70
    assert second.battery_status == "已充满"
    assert second.battery_power == "交流电供电"


def test_build_metrics_script_reads_sysfs_without_subshells():
    script = build_metrics_script()

    assert '$(cat "$z/type")' not in script
    assert '$(cat "$z/temp")' not in script
    assert '$(cat "$f")' not in script
    assert 'IFS= read -r' in script


def test_parse_rotation_falls_back_to_rotation_name():
    from adbtool.services.metrics import parse_rotation

    assert parse_rotation("mRotation=ROTATION_90") == 1
    assert parse_rotation("mCurrentOrientation=3") == 3


def test_parse_metrics_sample_tolerates_incomplete_output():
    sample = parse_metrics_sample("只读到了半行数据", "ABC")

    assert sample.serial == "ABC"
    assert sample.has_data is False
    assert sample.cpu_usage is None
    assert sample.memory_percent is None
    assert sample.battery_status == "未知"


class FakeProcess(QObject):
    finished = Signal(object)

    def __init__(self, script: str) -> None:
        super().__init__()
        self.script = script
        self.is_running = False
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class FakeAdb:
    def __init__(self) -> None:
        self.processes: list[FakeProcess] = []

    def shell(self, serial, script, timeout_ms=30000, record=True):
        process = FakeProcess(script)
        self.processes.append(process)
        return process


def test_metrics_monitor_emits_diffed_samples(qtbot):
    adb = FakeAdb()
    monitor = MetricsMonitor(adb, interval_ms=60000)
    samples = []
    monitor.sample_ready.connect(samples.append)

    monitor.set_device("ABC", 60000)
    qtbot.waitUntil(lambda: len(adb.processes) == 1, timeout=1000)
    first_process = adb.processes[0]

    first_process.finished.emit(
        ProcessResult(ok=True, exit_code=0, stdout=SAMPLE_ONE, stderr="")
    )
    assert len(samples) == 1
    assert samples[0].cpu_usage is None

    monitor.refresh()
    qtbot.waitUntil(lambda: len(adb.processes) == 2, timeout=1000)
    adb.processes[1].finished.emit(
        ProcessResult(ok=True, exit_code=0, stdout=SAMPLE_TWO, stderr="")
    )

    assert len(samples) == 2
    assert samples[1].cpu_usage == 20
    assert samples[1].serial == "ABC"
    assert monitor.last_sample is samples[1]
    monitor.stop()


def test_metrics_monitor_queues_refresh_requested_while_busy(qtbot):
    adb = FakeAdb()
    monitor = MetricsMonitor(adb, interval_ms=60000)
    samples = []
    monitor.sample_ready.connect(samples.append)

    monitor.set_device("ABC", 60000)
    qtbot.waitUntil(lambda: len(adb.processes) == 1, timeout=1000)
    first_process = adb.processes[0]

    monitor.refresh()
    assert len(adb.processes) == 1

    first_process.finished.emit(
        ProcessResult(ok=True, exit_code=0, stdout=SAMPLE_ONE, stderr="")
    )

    qtbot.waitUntil(lambda: len(adb.processes) == 2, timeout=1000)
    assert len(samples) == 1
    adb.processes[1].finished.emit(
        ProcessResult(ok=True, exit_code=0, stdout=SAMPLE_TWO, stderr="")
    )
    assert len(samples) == 2
    monitor.stop()


def test_metrics_monitor_discards_results_after_device_switch(qtbot):
    adb = FakeAdb()
    monitor = MetricsMonitor(adb, interval_ms=60000)
    samples = []
    monitor.sample_ready.connect(samples.append)

    monitor.set_device("ABC", 60000)
    qtbot.waitUntil(lambda: len(adb.processes) == 1, timeout=1000)
    old_process = adb.processes[0]

    monitor.set_device("XYZ", 60000)
    qtbot.waitUntil(lambda: len(adb.processes) == 2, timeout=1000)
    old_process.finished.emit(
        ProcessResult(ok=True, exit_code=0, stdout=SAMPLE_ONE, stderr="")
    )

    assert samples == []
    assert old_process.cancelled is True
    monitor.stop()
