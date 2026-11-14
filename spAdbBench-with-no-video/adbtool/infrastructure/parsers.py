from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DeviceInfo:
    serial: str
    state: str
    model: str = ""
    product: str = ""
    transport_id: str = ""

    @property
    def connected(self) -> bool:
        return self.state == "device"

    @property
    def display_name(self) -> str:
        return self.model or self.serial


@dataclass(frozen=True)
class BatteryInfo:
    level: int | None = None
    temperature_c: float | None = None
    voltage_mv: int | None = None
    status: int | None = None
    health: int | None = None
    ac: bool = False
    usb: bool = False
    wireless: bool = False
    raw: dict[str, str] = field(default_factory=dict)


def _int_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value.strip())
    except (TypeError, ValueError):
        return None


def parse_devices(text: str) -> list[DeviceInfo]:
    devices: list[DeviceInfo] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("List of devices") or line.startswith("adb server"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        fields: dict[str, str] = {}
        for token in parts[2:]:
            if ":" in token:
                key, value = token.split(":", 1)
                fields[key] = value
        devices.append(
            DeviceInfo(
                serial=serial,
                state=state,
                model=fields.get("model", "").replace("_", " "),
                product=fields.get("product", ""),
                transport_id=fields.get("transport_id", ""),
            )
        )
    return devices


def parse_packages(text: str) -> list[str]:
    packages: list[str] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith("package:"):
            packages.append(line[len("package:") :])
    return packages


def parse_wm_size(text: str) -> tuple[str | None, str | None]:
    physical = None
    override = None
    for line in (text or "").splitlines():
        if "Physical size:" in line:
            physical = line.split(":", 1)[1].strip()
        elif "Override size:" in line:
            override = line.split(":", 1)[1].strip()
    effective = override or physical
    return effective, physical


def parse_wm_density(text: str) -> tuple[int | None, int | None]:
    physical = None
    override = None
    for line in (text or "").splitlines():
        if "Physical density:" in line:
            physical = _int_or_none(line.split(":", 1)[1])
        elif "Override density:" in line:
            override = _int_or_none(line.split(":", 1)[1])
    return override, physical


def parse_battery(text: str) -> BatteryInfo:
    raw: dict[str, str] = {}
    for line in (text or "").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        raw[key.strip()] = value.strip()

    temperature_raw = _int_or_none(raw.get("temperature"))
    return BatteryInfo(
        level=_int_or_none(raw.get("level")),
        temperature_c=temperature_raw / 10.0 if temperature_raw is not None else None,
        voltage_mv=_int_or_none(raw.get("voltage")),
        status=_int_or_none(raw.get("status")),
        health=_int_or_none(raw.get("health")),
        ac=raw.get("AC powered", "").lower() == "true",
        usb=raw.get("USB powered", "").lower() == "true",
        wireless=raw.get("Wireless powered", "").lower() == "true",
        raw=raw,
    )


def parse_props(text: str) -> dict[str, str]:
    props: dict[str, str] = {}
    bracket = re.compile(r"^\[([^\]]+)\]:\s*\[(.*)\]\s*$")
    for line in (text or "").splitlines():
        match = bracket.match(line.strip())
        if match:
            props[match.group(1)] = match.group(2)
    return props
