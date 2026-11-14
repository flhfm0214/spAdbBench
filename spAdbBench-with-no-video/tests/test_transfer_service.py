from pathlib import Path

import pytest

from adbtool.services.adb import AdbService
from adbtool.services.transfer import (
    TransferService,
    is_system_remote_path,
    parse_transfer_progress,
    remote_join,
)


def test_install_argv_with_flags(tmp_path):
    apk = tmp_path / "app.apk"
    apk.write_bytes(b"apk")
    service = TransferService(AdbService(Path("adb.exe")))
    assert service.install_argv("ABC", str(apk), reinstall=True, grant=True) == [
        "adb.exe",
        "-s",
        "ABC",
        "install",
        "-r",
        "-g",
        str(apk),
    ]


def test_install_argv_without_flags(tmp_path):
    apk = tmp_path / "app.apk"
    apk.write_bytes(b"apk")
    service = TransferService(AdbService(Path("adb.exe")))
    assert service.install_argv("ABC", str(apk), reinstall=False, grant=False) == [
        "adb.exe",
        "-s",
        "ABC",
        "install",
        str(apk),
    ]


def test_split_install_argv(tmp_path):
    base = tmp_path / "base.apk"
    split = tmp_path / "split1.apk"
    base.write_bytes(b"base")
    split.write_bytes(b"split")
    service = TransferService(AdbService(Path("adb.exe")))
    assert service.split_install_argv("ABC", [str(base), str(split)]) == [
        "adb.exe",
        "-s",
        "ABC",
        "install-multiple",
        "-r",
        str(base),
        str(split),
    ]


def test_push_and_pull_argv_keep_paths_as_arguments(tmp_path):
    local = tmp_path / "a b.txt"
    local.write_text("x", encoding="utf-8")
    remote = "/sdcard/Download/a b.txt"
    service = TransferService(AdbService(Path("adb.exe")))
    assert service.push_argv("ABC", str(local), remote) == [
        "adb.exe", "-s", "ABC", "push", str(local), remote
    ]
    assert service.pull_argv("ABC", remote, str(tmp_path / "out dir")) == [
        "adb.exe", "-s", "ABC", "pull", remote, str(tmp_path / "out dir")
    ]


def test_invalid_local_file_rejected(tmp_path):
    service = TransferService(AdbService(Path("adb.exe")))
    with pytest.raises(ValueError):
        service.install_argv("ABC", str(tmp_path / "missing.apk"))


def test_system_remote_path_detection():
    assert is_system_remote_path("/system/etc/hosts")
    assert is_system_remote_path("/vendor/lib64/libfoo.so")
    assert is_system_remote_path("/product/app")
    assert is_system_remote_path("/system_ext/etc")
    assert is_system_remote_path("/odm/etc")
    assert is_system_remote_path("/apex/com.android.foo")
    assert not is_system_remote_path("/sdcard/system/file")
    assert not is_system_remote_path("/data/local/tmp/file")


def test_progress_parser():
    assert parse_transfer_progress(" 45% /sdcard/Download/file") == 45
    assert parse_transfer_progress("1 file pushed, 0 skipped") is None
    assert parse_transfer_progress("100%") == 100


def test_remote_join():
    assert remote_join("/sdcard/Pictures/", "shot.png") == "/sdcard/Pictures/shot.png"
    assert remote_join("/sdcard/Pictures", "shot.png") == "/sdcard/Pictures/shot.png"
