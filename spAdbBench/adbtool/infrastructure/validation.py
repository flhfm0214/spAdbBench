from __future__ import annotations

import re


PACKAGE_RE = re.compile(r"^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*$")
SERIAL_RE = re.compile(r"^[A-Za-z0-9._:-]+$")


def validate_package(value: str) -> str:
    package = (value or "").strip()
    if not PACKAGE_RE.fullmatch(package):
        raise ValueError(f"包名不合法: {value!r}")
    return package


def validate_serial(value: str) -> str:
    serial = (value or "").strip()
    if not serial or len(serial) > 128 or not SERIAL_RE.fullmatch(serial):
        raise ValueError(f"设备序列号不合法: {value!r}")
    return serial


def validate_int(value, minimum: int, maximum: int, name: str = "数值") -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}必须是整数") from exc
    if number < minimum or number > maximum:
        raise ValueError(f"{name}必须在 {minimum} 到 {maximum} 之间")
    return number


def validate_number(value, minimum: float, maximum: float, name: str = "数值") -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}必须是数字") from exc
    if number < minimum or number > maximum:
        raise ValueError(f"{name}必须在 {minimum} 到 {maximum} 之间")
    return number


def validate_remote_path(value: str) -> str:
    path = (value or "").strip()
    if not path:
        raise ValueError("远端路径不能为空")
    if any(char in path for char in ("\x00", "\n", "\r")):
        raise ValueError("远端路径包含控制字符")
    return path


def quote_remote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"
