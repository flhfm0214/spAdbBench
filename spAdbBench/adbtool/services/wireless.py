from __future__ import annotations

import secrets
from dataclasses import dataclass

PAIRING_SERVICE = "_adb-tls-pairing._tcp"
CONNECT_SERVICE = "_adb-tls-connect._tcp"


@dataclass(frozen=True)
class MdnsService:
    name: str
    service_type: str
    address: str


def parse_mdns_services(text: str) -> list[MdnsService]:
    services: list[MdnsService] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line.lower().startswith("list of discovered"):
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        address = parts[-1]
        service_type = parts[-2]
        if ":" not in address or not service_type.startswith("_"):
            continue
        services.append(
            MdnsService(
                name=" ".join(parts[:-2]),
                service_type=service_type,
                address=address,
            )
        )
    return services


def find_service(
    services: list[MdnsService], service_type: str
) -> MdnsService | None:
    for service in services:
        if service.service_type == service_type:
            return service
    return None


def make_pairing_credentials() -> tuple[str, str, str]:
    """Return (name, password, WiFi QR payload) for Android QR pairing."""
    name = f"adb-utils-{secrets.token_hex(4)}"
    password = secrets.token_hex(8)
    payload = f"WIFI:T:ADB;S:{name};P:{password};;"
    return name, password, payload


__all__ = [
    "CONNECT_SERVICE",
    "MdnsService",
    "PAIRING_SERVICE",
    "find_service",
    "make_pairing_credentials",
    "parse_mdns_services",
]
