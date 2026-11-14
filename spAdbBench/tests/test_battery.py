from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Signal

from adbtool.infrastructure.process import ProcessResult
from adbtool.services.battery import (
    BatterySample,
    BatterySampler,
    BatteryService,
    export_csv,
    parse_battery_sample,
)
from adbtool.services.battery_state import BatterySimulationTracker


class FakeProcess(QObject):
    finished = Signal(object)

    def __init__(self, argv: list[str]) -> None:
        super().__init__()
        self.argv = tuple(argv)
        self.is_running = True
        self.cancelled = False

    def complete(self, *, ok: bool = True, stdout: str = "", stderr: str = "") -> None:
        self.is_running = False
        self.finished.emit(
            ProcessResult(
                ok=ok,
                exit_code=0 if ok else 1,
                stdout=stdout,
                stderr=stderr,
                args=self.argv,
            )
        )

    def cancel(self) -> None:
        self.cancelled = True
        self.is_running = False


class FakeAdb:
    def __init__(self) -> None:
        self.shells: list[tuple[str, str, FakeProcess]] = []

    def shell(self, serial, script, timeout_ms=30000, record=True):
        process = FakeProcess([serial, script])
        self.shells.append((serial, script, process))
        return process


def make_service(tmp_path):
    adb = FakeAdb()
    tracker = BatterySimulationTracker(tmp_path / "data" / "battery_simulation.json")
    return BatteryService(adb, tracker), adb, tracker


def test_set_level_command_and_tracker(tmp_path):
    service, adb, tracker = make_service(tmp_path)

    process = service.set_level("ABC", 55)

    assert adb.shells[0][1] == "dumpsys battery set level 55"
    assert tracker.state("ABC") is None
    process.complete()
    assert tracker.state("ABC")["level"] == 55


def test_temperature_converts_tenths(tmp_path):
    service, adb, tracker = make_service(tmp_path)

    process = service.set_temperature("ABC", 31.5)

    assert adb.shells[0][1] == "dumpsys battery set temp 315"
    process.complete()
    assert tracker.state("ABC")["temperature_c"] == 31.5


def test_invalid_values_do_not_run_commands(tmp_path):
    service, adb, _tracker = make_service(tmp_path)

    with pytest.raises(ValueError):
        service.set_level("ABC", 101)
    with pytest.raises(ValueError):
        service.set_status("ABC", 6)
    with pytest.raises(ValueError):
        service.set_charging("ABC", "solar", True)
    with pytest.raises(ValueError):
        service.set_temperature("ABC", 120)

    assert adb.shells == []


def test_reset_clears_tracker_only_after_success(tmp_path):
    service, adb, tracker = make_service(tmp_path)
    tracker.mark("ABC", {"level": 55})

    process = service.reset("ABC")
    assert tracker.state("ABC") == {"level": 55}

    process.complete()
    assert tracker.state("ABC") is None


def test_charging_and_unplug_commands(tmp_path):
    service, adb, tracker = make_service(tmp_path)

    service.set_charging("ABC", "usb", True).complete()
    service.unplug("ABC").complete()

    assert adb.shells[0][1] == "dumpsys battery set usb 1"
    assert adb.shells[1][1] == "dumpsys battery unplug"
    assert tracker.state("ABC")["unplugged"] is True


def test_charging_states_use_one_command_and_track_all_sources(tmp_path):
    service, adb, tracker = make_service(tmp_path)

    process = service.set_charging_states("ABC", ac=True, usb=False, wireless=True)

    assert adb.shells[0][1] == (
        "dumpsys battery set ac 1; "
        "dumpsys battery set usb 0; "
        "dumpsys battery set wireless 1"
    )
    process.complete()
    assert tracker.state("ABC")["ac"] is True
    assert tracker.state("ABC")["usb"] is False
    assert tracker.state("ABC")["wireless"] is True


def test_parse_battery_sample_maps_status_and_current():
    text = (
        "level: 55\n"
        "temperature: 301\n"
        "voltage: 4000\n"
        "status: 2\n"
        "current now: -123456\n"
    )

    sample = parse_battery_sample(text)

    assert sample.level == 55
    assert sample.temperature_c == 30.1
    assert sample.voltage_mv == 4000
    assert sample.status == "充电中"
    assert sample.current_now_ua == -123456


def test_export_csv_has_bom_and_columns(tmp_path):
    path = tmp_path / "battery.csv"
    export_csv(
        path,
        [
            BatterySample(
                "2026-11-13T20:00:00+08:00",
                55,
                30.1,
                4000,
                "充电中",
                -123456,
            )
        ],
    )

    raw = path.read_bytes()
    text = path.read_text(encoding="utf-8-sig")
    assert raw.startswith(b"\xef\xbb\xbf")
    assert "时间,电量,温度,电压,状态" in text
    assert "55" in text
    assert "充电中" in text


def test_sampler_reads_asynchronously_and_emits(qtbot):
    adb = FakeAdb()
    sampler = BatterySampler(adb, interval_ms=1000)
    samples = []
    sampler.sample.connect(samples.append)

    sampler.start("ABC", 1000)

    assert adb.shells[0][1] == "dumpsys battery"
    process = adb.shells[0][2]
    process.complete(stdout="level: 66\ntemperature: 300\nvoltage: 4100\nstatus: 2\n")

    assert len(samples) == 1
    assert samples[0].level == 66
    assert samples[0].status == "充电中"
    sampler.stop()


def test_sampler_stop_cancels_in_flight_process(qtbot):
    adb = FakeAdb()
    sampler = BatterySampler(adb, interval_ms=1000)
    sampler.start("ABC", 1000)
    process = adb.shells[0][2]

    sampler.stop()

    assert process.cancelled is True


def test_tracker_persists_and_clears(tmp_path):
    path = tmp_path / "battery.json"
    tracker = BatterySimulationTracker(path)
    tracker.mark("ABC", {"level": 55, "temperature_c": 30.0})

    reloaded = BatterySimulationTracker(path)
    assert reloaded.state("ABC")["level"] == 55

    reloaded.clear("ABC")
    assert BatterySimulationTracker(path).state("ABC") is None


def test_tracker_ignores_corrupt_file(tmp_path):
    path = tmp_path / "battery.json"
    path.write_text("{bad", encoding="utf-8")

    tracker = BatterySimulationTracker(path)

    assert tracker.state("ABC") is None
