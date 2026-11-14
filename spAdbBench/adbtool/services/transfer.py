from __future__ import annotations

import posixpath
import re
from pathlib import Path

from ..infrastructure.process import AdbProcess
from ..infrastructure.validation import quote_remote, validate_remote_path
from .adb import AdbService


SYSTEM_PREFIXES = ("/system", "/vendor", "/product", "/system_ext", "/odm", "/apex", "/init.rc")


def parse_transfer_progress(text: str) -> int | None:
    matches = re.findall(r"(\d{1,3})%", text or "")
    for value in reversed(matches):
        number = int(value)
        if 0 <= number <= 100:
            return number
    return None


def is_system_remote_path(path: str) -> bool:
    normalized = posixpath.normpath((path or "").strip())
    return any(
        normalized == prefix or normalized.startswith(prefix + "/")
        for prefix in SYSTEM_PREFIXES
    )


def remote_join(remote_dir: str, name: str) -> str:
    return (remote_dir or "").rstrip("/") + "/" + name


class TransferService:
    def __init__(self, adb: AdbService) -> None:
        self.adb = adb

    @staticmethod
    def _validate_apk(path: str | Path) -> Path:
        apk = Path(path).expanduser()
        if not apk.is_file():
            raise ValueError(f"APK 不存在: {apk}")
        if apk.suffix.lower() != ".apk":
            raise ValueError(f"不是 APK 文件: {apk.name}")
        return apk

    @staticmethod
    def _validate_local(path: str | Path) -> Path:
        local = Path(path).expanduser()
        if not local.exists():
            raise ValueError(f"本地路径不存在: {local}")
        return local

    def install_argv(
        self,
        serial: str,
        apk: str | Path,
        reinstall: bool = True,
        grant: bool = False,
    ) -> list[str]:
        apk_path = self._validate_apk(apk)
        flags: list[str] = []
        if reinstall:
            flags.append("-r")
        if grant:
            flags.append("-g")
        return self.adb.build(serial, "install", *flags, str(apk_path))

    def split_install_argv(
        self,
        serial: str,
        apks: list[str | Path],
        reinstall: bool = True,
        grant: bool = False,
    ) -> list[str]:
        if not apks:
            raise ValueError("至少选择一个拆分 APK")
        paths = [str(self._validate_apk(apk)) for apk in apks]
        flags: list[str] = []
        if reinstall:
            flags.append("-r")
        if grant:
            flags.append("-g")
        return self.adb.build(serial, "install-multiple", *flags, *paths)

    def install(
        self,
        serial: str,
        apk: str | Path,
        reinstall: bool = True,
        grant: bool = False,
    ) -> AdbProcess:
        return self.adb.run_argv(
            self.install_argv(serial, apk, reinstall=reinstall, grant=grant),
            timeout_ms=300000,
        )

    def install_split(
        self,
        serial: str,
        apks: list[str | Path],
        reinstall: bool = True,
        grant: bool = False,
    ) -> AdbProcess:
        return self.adb.run_argv(
            self.split_install_argv(serial, apks, reinstall=reinstall, grant=grant),
            timeout_ms=300000,
        )

    def push_argv(self, serial: str, local: str | Path, remote: str) -> list[str]:
        local_path = self._validate_local(local)
        remote_path = validate_remote_path(remote)
        return self.adb.build(serial, "push", str(local_path), remote_path)

    def pull_argv(self, serial: str, remote: str, local: str | Path) -> list[str]:
        remote_path = validate_remote_path(remote)
        return self.adb.build(serial, "pull", remote_path, str(Path(local).expanduser()))

    def push(self, serial: str, local: str | Path, remote: str) -> AdbProcess:
        return self.adb.run_argv(self.push_argv(serial, local, remote), timeout_ms=600000)

    def pull(self, serial: str, remote: str, local: str | Path) -> AdbProcess:
        return self.adb.run_argv(self.pull_argv(serial, remote, local), timeout_ms=600000)

    def screenshot_destination(self, local: str | Path, remote_dir: str) -> str:
        local_path = self._validate_local(local)
        remote_path = validate_remote_path(remote_dir)
        return remote_join(remote_path, local_path.name)

    def push_screenshot(
        self,
        serial: str,
        local: str | Path,
        remote_dir: str,
    ) -> tuple[AdbProcess, str]:
        destination = self.screenshot_destination(local, remote_dir)
        process = self.adb.run_argv(
            self.push_argv(serial, local, destination),
            timeout_ms=300000,
        )
        return process, destination

    def media_scan(self, serial: str, remote_file: str) -> AdbProcess:
        uri = quote_remote("file://" + remote_file)
        command = f"am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d {uri}"
        return self.adb.shell(serial, command, timeout_ms=15000)
