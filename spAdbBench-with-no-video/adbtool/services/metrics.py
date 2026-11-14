from __future__ import annotations

import re
import time
from dataclasses import dataclass, field, replace
from datetime import datetime

from PySide6.QtCore import QObject, QTimer, Signal

from ..infrastructure.parsers import parse_battery
from .adb import AdbService


MIN_INTERVAL_MS = 100
MAX_INTERVAL_MS = 60000

BATTERY_STATUS = {
    1: "未知",
    2: "充电中",
    3: "放电中",
    4: "未充电",
    5: "已充满",
}

BATTERY_HEALTH = {
    1: "未知",
    2: "良好",
    3: "过热",
    4: "损坏",
    5: "过压",
    6: "未指定故障",
    7: "过冷",
}

_MARKERS = {
    "__STAT__",
    "__FREQ__",
    "__MEM__",
    "__BATTERY__",
    "__LOAD__",
    "__UPTIME__",
    "__GLES__",
    "__PLATFORM__",
    "__MODEL__",
    "__EGL__",
    "__GLVER__",
    "__GPUFREQ__",
    "__THERMAL__",
    "__ROTATION__",
}

_FREQ_RE = re.compile(r"cpu(\d+)/cpufreq/(?:scaling|cpuinfo)_cur_freq\s+(\d+)")
_GLES_RE = re.compile(r"OpenGL ES\s+\d+(?:\.\d+)?")
_ROTATION_RE = re.compile(
    r"(?:SurfaceOrientation:\s*|mCurrentOrientation=|mDisplayRotation=|mRotation=)(\d+)"
)
_ROTATION_NAME_RE = re.compile(r"mRotation=ROTATION_(0|90|180|270)")
_CPU_THERMAL_KEYS = (
    "cpu",
    "soc",
    "tsens",
    "cluster",
    "big",
    "little",
    "prime",
    "gold",
    "silver",
)
_GPU_THERMAL_KEYS = ("gpu", "kgsl", "adreno", "mali")


def _is_cpu0_sensor(name: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", name.lower())
    return normalized.startswith("cpu0")


def build_metrics_script(
    include_static: bool = False,
    include_battery: bool = True,
) -> str:
    # Command substitution forks a shell for every sysfs file. Some devices
    # (for example the OnePlus 6) then need ~3 s per thermal sweep, which caps
    # the sampling rate no matter what interval the user configured.
    script = (
        "echo __STAT__; "
        'while IFS= read -r line; do case "$line" in cpu*) echo "$line";; esac; done '
        "< /proc/stat; "
        "echo __FREQ__; "
        'for c in /sys/devices/system/cpu/cpu[0-9]*; do '
        'f="$c/cpufreq/scaling_cur_freq"; '
        '[ -r "$f" ] || f="$c/cpufreq/cpuinfo_cur_freq"; '
        '[ -r "$f" ] || continue; IFS= read -r v < "$f"; echo "$f $v"; '
        "done 2>/dev/null; "
        "echo __GPUFREQ__; "
        'for f in /sys/class/kgsl/kgsl-3d0/gpuclk '
        '/sys/class/kgsl/kgsl-3d0/devfreq/cur_freq '
        '/sys/kernel/gpu/gpu_freq; do '
        '[ -r "$f" ] || continue; IFS= read -r v < "$f"; echo "$f $v"; '
        "done 2>/dev/null; "
        'for d in /sys/class/devfreq/*; do '
        'case "$d" in *gpu*|*GPU*|*mali*|*Mali*|*kgsl*|*KGSL*) '
        'f="$d/cur_freq"; [ -r "$f" ] || continue; '
        'IFS= read -r v < "$f"; echo "$f $v";; esac; '
        "done 2>/dev/null; "
        "echo __THERMAL__; "
        'for z in /sys/class/thermal/thermal_zone*; do '
        '[ -r "$z/type" ] && [ -r "$z/temp" ] || continue; '
        'IFS= read -r t < "$z/type"; IFS= read -r v < "$z/temp"; '
        'echo "$t|$v"; done 2>/dev/null; '
        "echo __MEM__; cat /proc/meminfo; "
        + ("echo __BATTERY__; dumpsys battery; " if include_battery else "")
        + "echo __LOAD__; cat /proc/loadavg; "
        "echo __UPTIME__; cat /proc/uptime"
    )
    if include_static:
        script += (
            "; echo __GLES__; dumpsys SurfaceFlinger 2>/dev/null | grep -m1 '^GLES:'; "
            "echo __PLATFORM__; getprop ro.board.platform; "
            "echo __MODEL__; getprop ro.product.model; "
            "echo __EGL__; getprop ro.hardware.egl; "
            "echo __GLVER__; getprop ro.opengles.version"
        )
    return script


@dataclass(frozen=True)
class CpuTimes:
    name: str
    total: int
    idle: int


@dataclass(frozen=True)
class CpuCore:
    index: int
    frequency_mhz: int | None = None
    usage_percent: int | None = None


@dataclass(frozen=True)
class SensorTemperature:
    name: str
    celsius: float


@dataclass(frozen=True)
class MetricsSample:
    serial: str
    captured_at: datetime
    cpu_usage: int | None
    cores: tuple[CpuCore, ...]
    cpu_times: tuple[CpuTimes, ...] = field(repr=False, compare=False)
    memory_total_kb: int = 0
    memory_available_kb: int = 0
    swap_total_kb: int = 0
    swap_free_kb: int = 0
    load_1: float | None = None
    load_5: float | None = None
    load_15: float | None = None
    uptime_seconds: int | None = None
    battery_level: int | None = None
    battery_status: str = "未知"
    battery_health: str = "未知"
    battery_temperature_c: float | None = None
    battery_voltage_mv: int | None = None
    battery_power: str = "未接电源"
    platform: str = ""
    model: str = ""
    gpu_renderer: str = ""
    gpu_vendor: str = ""
    gles_version: str = ""
    gpu_frequency_mhz: int | None = None
    sensor_temperatures: tuple[SensorTemperature, ...] = ()
    display_rotation: int | None = None

    @property
    def memory_used_kb(self) -> int:
        return max(0, self.memory_total_kb - self.memory_available_kb)

    @property
    def memory_percent(self) -> int | None:
        if self.memory_total_kb <= 0:
            return None
        used = self.memory_used_kb
        return max(0, min(100, round(used * 100 / self.memory_total_kb)))

    @property
    def max_frequency_mhz(self) -> int | None:
        values = [core.frequency_mhz for core in self.cores if core.frequency_mhz]
        return max(values) if values else None

    @property
    def average_frequency_mhz(self) -> int | None:
        values = [core.frequency_mhz for core in self.cores if core.frequency_mhz]
        if not values:
            return None
        return round(sum(values) / len(values))

    @property
    def cpu_temperature_c(self) -> float | None:
        cpu0_values = [
            item.celsius
            for item in self.sensor_temperatures
            if _is_cpu0_sensor(item.name)
        ]
        if cpu0_values:
            return max(cpu0_values)
        values = [
            item.celsius
            for item in self.sensor_temperatures
            if any(key in item.name.lower() for key in _CPU_THERMAL_KEYS)
        ]
        return max(values) if values else None

    @property
    def gpu_temperature_c(self) -> float | None:
        values = [
            item.celsius
            for item in self.sensor_temperatures
            if any(key in item.name.lower() for key in _GPU_THERMAL_KEYS)
        ]
        return max(values) if values else None

    @property
    def has_data(self) -> bool:
        return bool(
            self.cores
            or self.memory_total_kb
            or self.battery_level is not None
            or self.sensor_temperatures
            or self.display_rotation is not None
        )


def _split_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if line in _MARKERS:
            current = line
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(raw_line)
    return {key: "\n".join(lines) for key, lines in sections.items()}


def _parse_cpu_times(text: str) -> tuple[CpuTimes, ...]:
    times: list[CpuTimes] = []
    for line in (text or "").splitlines():
        parts = line.split()
        if not parts or not re.fullmatch(r"cpu\d*", parts[0]):
            continue
        values: list[int] = []
        for raw in parts[1:9]:
            try:
                values.append(int(raw))
            except ValueError:
                values.append(0)
        if len(values) < 4:
            continue
        values.extend([0] * (8 - len(values)))
        times.append(
            CpuTimes(
                name=parts[0],
                total=sum(values[:8]),
                idle=values[3] + values[4],
            )
        )
    return tuple(times)


def _parse_frequencies(text: str) -> dict[int, int]:
    frequencies: dict[int, int] = {}
    for match in _FREQ_RE.finditer(text or ""):
        index = int(match.group(1))
        khz = int(match.group(2))
        if khz > 0:
            frequencies[index] = round(khz / 1000)
    return frequencies


def _frequency_to_mhz(value: int) -> int | None:
    if value <= 0:
        return None
    if value >= 100_000_000:
        return round(value / 1_000_000)
    if value >= 1_000_000:
        return round(value / 1_000)
    return value


def _parse_gpu_frequency(text: str) -> int | None:
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        path = parts[0].lower()
        if not any(key in path for key in ("gpu", "kgsl", "mali", "adreno")):
            continue
        try:
            value = int(parts[1])
        except ValueError:
            continue
        mhz = _frequency_to_mhz(value)
        if mhz:
            return mhz
    return None


def parse_rotation(text: str) -> int | None:
    raw = text or ""
    match = _ROTATION_RE.search(raw)
    if match is not None:
        value = int(match.group(1))
        return value if 0 <= value <= 3 else None
    named = _ROTATION_NAME_RE.search(raw)
    if named is None:
        return None
    return int(named.group(1)) // 90


def _parse_thermal(text: str) -> tuple[SensorTemperature, ...]:
    values: dict[str, float] = {}
    for line in (text or "").splitlines():
        if "|" not in line:
            continue
        name, raw_value = line.rsplit("|", 1)
        name = name.strip()
        if not name:
            continue
        try:
            raw = int(raw_value.strip())
        except ValueError:
            continue
        if abs(raw) >= 1000:
            celsius = raw / 1000
        elif abs(raw) > 200:
            celsius = raw / 10
        else:
            celsius = float(raw)
        if not -40 <= celsius <= 150:
            continue
        values[name] = max(values.get(name, celsius), celsius)
    return tuple(
        SensorTemperature(name=name, celsius=round(celsius, 1))
        for name, celsius in sorted(values.items())
    )


def _parse_meminfo(text: str) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in (text or "").splitlines():
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        parts = raw_value.strip().split()
        if not parts:
            continue
        try:
            values[key.strip()] = int(parts[0])
        except ValueError:
            continue
    return values


def _usage_percent(current: CpuTimes, previous: CpuTimes | None) -> int | None:
    if previous is None:
        return None
    total_delta = current.total - previous.total
    idle_delta = current.idle - previous.idle
    if total_delta <= 0 or idle_delta < 0:
        return None
    busy_delta = max(0, total_delta - idle_delta)
    return max(0, min(100, round(busy_delta * 100 / total_delta)))


def _parse_gles(text: str) -> tuple[str, str, str]:
    for line in (text or "").splitlines():
        if not line.strip().startswith("GLES:"):
            continue
        payload = line.split(":", 1)[1].strip()
        parts = [part.strip() for part in payload.split(",", 2)]
        vendor = parts[0] if parts else ""
        renderer = parts[1] if len(parts) > 1 else ""
        version_text = parts[2] if len(parts) > 2 else ""
        match = _GLES_RE.search(version_text)
        return vendor, renderer, match.group(0) if match else ""
    return "", "", ""


def _gles_version_from_prop(text: str) -> str:
    raw = (text or "").strip()
    try:
        value = int(raw)
    except ValueError:
        return ""
    if value <= 0:
        return ""
    return f"OpenGL ES {value >> 16}.{value & 0xFFFF}"


def _battery_power(info) -> str:
    sources = []
    if info.ac:
        sources.append("交流电供电")
    if info.usb:
        sources.append("USB 供电")
    if info.wireless:
        sources.append("无线充电")
    return "、".join(sources) if sources else "未接电源"


def parse_metrics_sample(
    text: str,
    serial: str,
    previous: tuple[CpuTimes, ...] | None = None,
) -> MetricsSample:
    sections = _split_sections(text)
    cpu_times = _parse_cpu_times(sections.get("__STAT__", ""))
    previous_by_name = {item.name: item for item in (previous or ())}
    usage_by_name = {
        item.name: _usage_percent(item, previous_by_name.get(item.name))
        for item in cpu_times
    }

    frequencies = _parse_frequencies(sections.get("__FREQ__", ""))
    core_indices = {
        int(item.name[3:])
        for item in cpu_times
        if item.name != "cpu" and item.name[3:].isdigit()
    }
    core_indices.update(frequencies)
    cores = tuple(
        CpuCore(
            index=index,
            frequency_mhz=frequencies.get(index),
            usage_percent=usage_by_name.get(f"cpu{index}"),
        )
        for index in sorted(core_indices)
    )

    memory = _parse_meminfo(sections.get("__MEM__", ""))
    memory_total = memory.get("MemTotal", 0)
    memory_available = memory.get("MemAvailable")
    if memory_available is None:
        memory_available = (
            memory.get("MemFree", 0)
            + memory.get("Buffers", 0)
            + memory.get("Cached", 0)
        )

    load_parts = (sections.get("__LOAD__", "").strip().split())
    load_values: list[float | None] = []
    for raw in load_parts[:3]:
        try:
            load_values.append(float(raw))
        except ValueError:
            load_values.append(None)
    while len(load_values) < 3:
        load_values.append(None)
    load_1, load_5, load_15 = load_values

    uptime_seconds = None
    uptime_parts = sections.get("__UPTIME__", "").strip().split()
    if uptime_parts:
        try:
            uptime_seconds = int(float(uptime_parts[0]))
        except ValueError:
            pass

    battery = parse_battery(sections.get("__BATTERY__", ""))
    gpu_vendor, gpu_renderer, gles_version = _parse_gles(sections.get("__GLES__", ""))
    if not gpu_renderer:
        gpu_renderer = sections.get("__EGL__", "").strip()
    if not gles_version:
        gles_version = _gles_version_from_prop(sections.get("__GLVER__", ""))

    return MetricsSample(
        serial=serial,
        captured_at=datetime.now().astimezone(),
        cpu_usage=usage_by_name.get("cpu"),
        cores=cores,
        cpu_times=cpu_times,
        memory_total_kb=memory_total,
        memory_available_kb=memory_available,
        swap_total_kb=memory.get("SwapTotal", 0),
        swap_free_kb=memory.get("SwapFree", 0),
        load_1=load_1,
        load_5=load_5,
        load_15=load_15,
        uptime_seconds=uptime_seconds,
        battery_level=battery.level,
        battery_status=BATTERY_STATUS.get(battery.status, "未知"),
        battery_health=BATTERY_HEALTH.get(battery.health, "未知"),
        battery_temperature_c=battery.temperature_c,
        battery_voltage_mv=battery.voltage_mv,
        battery_power=_battery_power(battery),
        platform=sections.get("__PLATFORM__", "").strip(),
        model=sections.get("__MODEL__", "").strip(),
        gpu_renderer=gpu_renderer,
        gpu_vendor=gpu_vendor,
        gles_version=gles_version,
        gpu_frequency_mhz=_parse_gpu_frequency(sections.get("__GPUFREQ__", "")),
        sensor_temperatures=_parse_thermal(sections.get("__THERMAL__", "")),
        display_rotation=parse_rotation(sections.get("__ROTATION__", "")),
    )


def clamp_interval(interval_ms: int) -> int:
    try:
        value = int(interval_ms)
    except (TypeError, ValueError):
        return 1000
    if value <= 0:
        return 0
    return max(MIN_INTERVAL_MS, min(MAX_INTERVAL_MS, value))


class MetricsMonitor(QObject):
    sample_ready = Signal(object)
    sample_failed = Signal(str)

    def __init__(
        self,
        adb: AdbService,
        interval_ms: int = 1000,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.adb = adb
        self._interval_ms = clamp_interval(interval_ms)
        self._serial = ""
        self._process = None
        self._pending_refresh = False
        self._epoch = 0
        self._previous_times: tuple[CpuTimes, ...] | None = None
        self._last_sample: MetricsSample | None = None
        self._last_error = ""
        self._static_serial = ""
        self._static: dict[str, str] = {}
        self._battery_serial = ""
        self._battery_at = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(self._interval_ms)
        self._timer.timeout.connect(self.refresh)

    @property
    def interval_ms(self) -> int:
        return self._interval_ms

    @property
    def serial(self) -> str:
        return self._serial

    @property
    def last_sample(self) -> MetricsSample | None:
        return self._last_sample

    def set_device(self, serial: str | None, interval_ms: int | None = None) -> None:
        target = serial or ""
        if interval_ms is not None:
            self.set_interval(interval_ms)
        if target == self._serial:
            if target and self._interval_ms > 0 and not self._timer.isActive():
                self._timer.start()
                QTimer.singleShot(0, self.refresh)
            return
        self.stop()
        if not target:
            return
        self._serial = target
        self._previous_times = None
        self._last_error = ""
        if self._interval_ms > 0:
            self._timer.start()
            QTimer.singleShot(0, self.refresh)

    def set_interval(self, interval_ms: int) -> None:
        self._interval_ms = clamp_interval(interval_ms)
        if self._interval_ms <= 0:
            self._pending_refresh = False
            self._timer.stop()
            return
        self._timer.setInterval(self._interval_ms)
        if self._serial and not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._epoch += 1
        self._timer.stop()
        process = self._process
        self._process = None
        self._pending_refresh = False
        if process is not None:
            process.cancel()
        self._serial = ""
        self._previous_times = None
        self._last_sample = None
        self._last_error = ""
        self._battery_serial = ""
        self._battery_at = 0.0

    def refresh(self) -> None:
        if not self._serial:
            return
        if self._process is not None:
            self._pending_refresh = True
            return
        self._pending_refresh = False
        serial = self._serial
        epoch = self._epoch
        now = time.monotonic()
        include_static = self._static_serial != serial
        include_battery = (
            self._battery_serial != serial or now - self._battery_at >= 10.0
        )
        process = self.adb.shell(
            serial,
            build_metrics_script(
                include_static=include_static,
                include_battery=include_battery,
            ),
            timeout_ms=15000,
            record=False,
        )
        self._process = process
        process.finished.connect(
            lambda result, s=serial, e=epoch, st=include_static, b=include_battery, p=process: (
                self._on_finished(s, e, st, b, p, result)
            )
        )

    def _on_finished(
        self,
        serial,
        epoch,
        include_static,
        include_battery,
        process,
        result,
    ) -> None:
        if self._process is not process:
            return
        self._process = None
        if epoch != self._epoch or serial != self._serial:
            self._pending_refresh = False
            return
        if result.cancelled:
            self._pending_refresh = False
            return
        if not result.ok:
            message = (result.stderr or result.stdout).strip() or "采样命令执行失败"
            self._report_failure(message)
            self._run_pending_refresh()
            return

        sample = parse_metrics_sample(
            result.stdout,
            serial,
            previous=self._previous_times,
        )
        if include_battery:
            self._battery_serial = serial
            self._battery_at = time.monotonic()
        elif self._last_sample is not None and self._last_sample.serial == serial:
            previous_sample = self._last_sample
            sample = replace(
                sample,
                battery_level=previous_sample.battery_level,
                battery_status=previous_sample.battery_status,
                battery_health=previous_sample.battery_health,
                battery_temperature_c=previous_sample.battery_temperature_c,
                battery_voltage_mv=previous_sample.battery_voltage_mv,
                battery_power=previous_sample.battery_power,
            )
        if include_static:
            self._static_serial = serial
            self._static = {
                "platform": sample.platform,
                "model": sample.model,
                "gpu_renderer": sample.gpu_renderer,
                "gpu_vendor": sample.gpu_vendor,
                "gles_version": sample.gles_version,
            }
        elif self._static_serial == serial:
            sample = replace(
                sample,
                platform=self._static.get("platform") or sample.platform,
                model=self._static.get("model") or sample.model,
                gpu_renderer=self._static.get("gpu_renderer") or sample.gpu_renderer,
                gpu_vendor=self._static.get("gpu_vendor") or sample.gpu_vendor,
                gles_version=self._static.get("gles_version") or sample.gles_version,
            )

        if not sample.has_data:
            self._report_failure("未读取到有效的性能数据")
            self._run_pending_refresh()
            return

        self._previous_times = sample.cpu_times
        self._last_sample = sample
        self._last_error = ""
        self.sample_ready.emit(sample)
        self._run_pending_refresh()

    def _run_pending_refresh(self) -> None:
        if not self._pending_refresh:
            return
        self._pending_refresh = False
        if self._serial:
            QTimer.singleShot(0, self.refresh)

    def _report_failure(self, message: str) -> None:
        if message == self._last_error:
            return
        self._last_error = message
        self.sample_failed.emit(message)
