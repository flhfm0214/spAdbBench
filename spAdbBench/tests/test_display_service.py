from pathlib import Path

import pytest

from adbtool.services.adb import AdbService
from adbtool.services.display import (
    DisplayInfo,
    DisplayService,
    parse_display_info,
    screenshot_destination,
)


def make_service() -> DisplayService:
    return DisplayService(AdbService(Path("adb.exe")))


def test_parse_display_info_reads_overrides():
    text = (
        "__SIZE__\n"
        "Physical size: 1080x2400\n"
        "Override size: 720x1600\n"
        "__DENSITY__\n"
        "Physical density: 420\n"
        "Override density: 320\n"
    )

    info = parse_display_info(text)

    assert info == DisplayInfo(
        effective_size="720x1600",
        physical_size="1080x2400",
        effective_density=320,
        physical_density=420,
        size_overridden=True,
        density_overridden=True,
    )


def test_parse_display_info_without_overrides():
    text = (
        "__SIZE__\n"
        "Physical size: 1080x2400\n"
        "__DENSITY__\n"
        "Physical density: 420\n"
    )

    info = parse_display_info(text)

    assert info.effective_size == "1080x2400"
    assert info.effective_density == 420
    assert info.size_overridden is False
    assert info.density_overridden is False


def test_info_argv_collects_size_and_density():
    service = make_service()

    assert service.info_argv("ABC") == [
        "adb.exe",
        "-s",
        "ABC",
        "shell",
        "echo __SIZE__; wm size; echo __DENSITY__; wm density",
    ]


def test_set_and_reset_size_argv():
    service = make_service()

    assert service.set_size_argv("ABC", 1080, 2400) == [
        "adb.exe",
        "-s",
        "ABC",
        "shell",
        "wm size 1080x2400",
    ]
    assert service.reset_size_argv("ABC") == [
        "adb.exe",
        "-s",
        "ABC",
        "shell",
        "wm size reset",
    ]


def test_set_and_reset_density_argv():
    service = make_service()

    assert service.set_density_argv("ABC", 420) == [
        "adb.exe",
        "-s",
        "ABC",
        "shell",
        "wm density 420",
    ]
    assert service.reset_density_argv("ABC") == [
        "adb.exe",
        "-s",
        "ABC",
        "shell",
        "wm density reset",
    ]


def test_invalid_display_values_are_rejected():
    service = make_service()

    with pytest.raises(ValueError):
        service.set_size_argv("ABC", 100, 2400)
    with pytest.raises(ValueError):
        service.set_size_argv("ABC", 1080, 10001)
    with pytest.raises(ValueError):
        service.set_density_argv("ABC", 71)


def test_key_argv_uses_registered_keycode():
    service = make_service()

    assert service.key_argv("ABC", "home") == [
        "adb.exe",
        "-s",
        "ABC",
        "shell",
        "input keyevent 3",
    ]
    with pytest.raises(ValueError):
        service.key_argv("ABC", "not-a-key")


def test_screenshot_argv_and_destination(tmp_path):
    service = make_service()

    assert service.screenshot_argv("ABC") == [
        "adb.exe",
        "-s",
        "ABC",
        "exec-out",
        "screencap",
        "-p",
    ]
    destination = screenshot_destination(
        "192.168.1.2:5555", tmp_path, timestamp="20260101-120000"
    )
    assert destination == tmp_path / "192.168.1.2_5555-20260101-120000.png"


def test_screenshot_requires_png_suffix(tmp_path):
    service = make_service()

    with pytest.raises(ValueError):
        service.screenshot("ABC", tmp_path / "shot.jpg")

