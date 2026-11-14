from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QObject, QTimer, Signal

from ..infrastructure.parsers import parse_battery
from ..infrastructure.validation import validate_int, validate_number
from .battery_state import BatterySimulationTracker


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


@dataclass(frozen=True)
class BatterySample:
    timestamp: str
    level: int | None
    temperature_c: float | None
    voltage_mv: int | None
    status: str
    current_now_ua: int | None = None


def battery_status_text(status: int | None) -> str:
    return BATTERY_STATUS.get(status, "未知")


def battery_health_text(health: int | None) -> str:
    return BATTERY_HEALTH.get(health, "未知")


def _int_or_none(value: str | None) -> int | None:
    try:
        return int((value or "").strip())
    except ValueError:
        return None


def parse_battery_sample(text: str) -> BatterySample:
    info = parse_battery(text)
    return BatterySample(
        timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
        level=info.level,
        temperature_c=info.temperature_c,
        voltage_mv=info.voltage_mv,
        status=battery_status_text(info.status),
        current_now_ua=_int_or_none(info.raw.get("current now")),
    )


def export_csv(path, samples: list[BatterySample]) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["时间", "电量", "温度", "电压", "状态", "电流"])
        for sample in samples:
            writer.writerow(
                [
                    sample.timestamp,
                    "" if sample.level is None else sample.level,
                    "" if sample.temperature_c is None else sample.temperature_c,
                    "" if sample.voltage_mv is None else sample.voltage_mv,
                    sample.status,
                    "" if sample.current_now_ua is None else sample.current_now_ua,
                ]
            )


class BatteryService(QObject):
    def __init__(
        self,
        adb,
        tracker: BatterySimulationTracker,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.adb = adb
        self.tracker = tracker

    def info(self, serial: str, *, timeout_ms: int = 15000):
        return self.adb.shell(
            serial,
            "dumpsys battery",
            timeout_ms=timeout_ms,
        )

    def set_level(self, serial: str, level: int):
        value = validate_int(level, 0, 100, "电量")
        return self._write(
            serial,
            f"dumpsys battery set level {value}",
            {"level": value, "unplugged": False},
        )

    def set_temperature(self, serial: str, celsius: float):
        value = validate_number(celsius, -20, 100, "温度")
        tenths = int(round(value * 10))
        return self._write(
            serial,
            f"dumpsys battery set temp {tenths}",
            {"temperature_c": value},
        )

    def set_status(self, serial: str, status: int):
        value = validate_int(status, 1, 5, "电池状态")
        return self._write(
            serial,
            f"dumpsys battery set status {value}",
            {"status": value},
        )

    def set_charging(self, serial: str, source: str, enabled: bool):
        if source not in {"ac", "usb", "wireless"}:
            raise ValueError(f"充电来源不合法: {source!r}")
        flag = 1 if enabled else 0
        return self._write(
            serial,
            f"dumpsys battery set {source} {flag}",
            {source: bool(enabled), "unplugged": False},
        )

    def set_charging_states(
        self,
        serial: str,
        ac: bool,
        usb: bool,
        wireless: bool,
    ):
        command = "; ".join(
            [
                f"dumpsys battery set ac {1 if ac else 0}",
                f"dumpsys battery set usb {1 if usb else 0}",
                f"dumpsys battery set wireless {1 if wireless else 0}",
            ]
        )
        return self._write(
            serial,
            command,
            {
                "ac": bool(ac),
                "usb": bool(usb),
                "wireless": bool(wireless),
                "unplugged": False,
            },
        )

    def unplug(self, serial: str):
        return self._write(
            serial,
            "dumpsys battery unplug",
            {
                "unplugged": True,
                "ac": False,
                "usb": False,
                "wireless": False,
            },
        )

    def reset(self, serial: str):
        process = self.adb.shell(serial, "dumpsys battery reset", timeout_ms=15000)

        def _clear(result) -> None:
            if result.ok:
                self.tracker.clear(serial)

        process.finished.connect(_clear)
        return process

    def _write(self, serial: str, command: str, values: dict):
        process = self.adb.shell(serial, command, timeout_ms=15000)

        def _record(result) -> None:
            if result.ok:
                self.tracker.mark(serial, values)

        process.finished.connect(_record)
        return process


class BatterySampler(QObject):
    sample = Signal(object)
    error = Signal(str)
    state = Signal(str)

    def __init__(
        self,
        adb,
        interval_ms: int = 1000,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.adb = adb
        self._serial = ""
        self._process = None
        self._epoch = 0
        self._interval_ms = max(1000, min(60000, int(interval_ms)))
        self._timer = QTimer(self)
        self._timer.setInterval(self._interval_ms)
        self._timer.timeout.connect(self.refresh)

    @property
    def serial(self) -> str:
        return self._serial

    @property
    def interval_ms(self) -> int:
        return self._interval_ms

    @property
    def is_running(self) -> bool:
        return self._timer.isActive()

    def start(self, serial: str, interval_ms: int = 1000) -> None:
        self.stop()
        self._serial = serial
        self._interval_ms = max(1000, min(60000, int(interval_ms)))
        self._timer.setInterval(self._interval_ms)
        self._timer.start()
        self.state.emit("采样中")
        self.refresh()

    def stop(self) -> None:
        self._epoch += 1
        self._timer.stop()
        process = self._process
        self._process = None
        if process is not None and process.is_running:
            process.cancel()
        if self._serial:
            self.state.emit("已停止")
        self._serial = ""

    def refresh(self) -> None:
        if not self._serial or self._process is not None:
            return
        serial = self._serial
        epoch = self._epoch
        process = self.adb.shell(
            serial,
            "dumpsys battery",
            timeout_ms=10000,
            record=False,
        )
        self._process = process
        process.finished.connect(
            lambda result, s=serial, e=epoch: self._on_finished(s, e, result)
        )

    def _on_finished(self, serial: str, epoch: int, result) -> None:
        if epoch != self._epoch or serial != self._serial:
            return
        self._process = None
        if result.cancelled:
            return
        if not result.ok:
            self.error.emit(
                (result.stderr or result.stdout).strip() or "电池采样失败"
            )
            return
        self.sample.emit(parse_battery_sample(result.stdout))
