from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from ..infrastructure.process import AdbProcess
from ..infrastructure.validation import validate_package
from .adb import AdbService


GOOGLE_PACKAGES = [
    "com.google.android.gms",
    "com.google.android.gsf",
    "com.google.android.gsf.login",
    "com.android.vending",
    "com.google.android.gm",
    "com.google.android.youtube",
    "com.google.android.apps.maps",
    "com.google.android.apps.photos",
    "com.google.android.googlequicksearchbox",
    "com.google.android.syncadapters.contacts",
    "com.google.android.syncadapters.calendar",
    "com.google.android.backuptransport",
    "com.google.android.partnersetup",
    "com.google.android.feedback",
    "com.google.android.tts",
]

_LIST_SCRIPT = (
    "echo __ADBTOOL_ALL__; pm list packages; "
    "echo __ADBTOOL_DISABLED__; pm list packages -d; "
    "echo __ADBTOOL_SYSTEM__; pm list packages -s; "
    "echo __ADBTOOL_END__"
)

_ACTION_COMMANDS = {
    "enable": "pm enable {package}",
    "disable": "pm disable-user --user 0 {package}",
    "launch": "monkey -p {package} -c android.intent.category.LAUNCHER 1",
    "restart": (
        "am force-stop {package}; "
        "monkey -p {package} -c android.intent.category.LAUNCHER 1"
    ),
    "force_stop": "am force-stop {package}",
    "clear": "pm clear {package}",
    "uninstall": "pm uninstall {package}",
    "uninstall_keep": "pm uninstall -k {package}",
    "restore": "pm install-existing --user 0 {package}; pm enable {package}",
    "info": "dumpsys package {package}",
    "path": "pm path {package}",
}


@dataclass(frozen=True)
class PackageInfo:
    package: str
    enabled: bool = True
    system: bool = False


@dataclass(frozen=True)
class BatchItemResult:
    package: str
    ok: bool
    output: str


@dataclass(frozen=True)
class ExtractItemResult:
    remote: str
    local: str
    ok: bool
    output: str
    package: str = ""


def parse_package_listing(text: str) -> list[PackageInfo]:
    sections: dict[str, set[str]] = {"all": set(), "disabled": set(), "system": set()}
    current = ""
    saw_marker = False
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if line == "__ADBTOOL_ALL__":
            current = "all"
            saw_marker = True
            continue
        if line == "__ADBTOOL_DISABLED__":
            current = "disabled"
            saw_marker = True
            continue
        if line == "__ADBTOOL_SYSTEM__":
            current = "system"
            saw_marker = True
            continue
        if line == "__ADBTOOL_END__":
            current = ""
            continue
        if not line.startswith("package:"):
            continue
        package = line[len("package:") :].strip()
        if not package:
            continue
        if not saw_marker:
            sections["all"].add(package)
        elif current in sections:
            sections[current].add(package)

    names = sections["all"] | sections["disabled"]
    return [
        PackageInfo(
            package=name,
            enabled=name not in sections["disabled"],
            system=name in sections["system"],
        )
        for name in sorted(names)
    ]


def parse_foreground(text: str) -> tuple[str, str]:
    import re

    patterns = [
        r"mResumedActivity:.*?ActivityRecord\{[^}]*?\s([A-Za-z0-9_.]+)/([A-Za-z0-9_.$]+)",
        r"topResumedActivity=ActivityRecord\{[^}]*?\s([A-Za-z0-9_.]+)/([A-Za-z0-9_.$]+)",
        r"mFocusedApp=.*?ActivityRecord\{[^}]*?\s([A-Za-z0-9_.]+)/([A-Za-z0-9_.$]+)",
        r"mCurrentFocus=.*?\s([A-Za-z0-9_.]+)/([A-Za-z0-9_.$]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text or "")
        if match:
            return match.group(1), match.group(2)
    return "", ""


def parse_pm_path(text: str) -> list[str]:
    paths: list[str] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if line.startswith("package:"):
            path = line[len("package:") :].strip()
            if path:
                paths.append(path)
    return paths


def filter_packages(packages: list[PackageInfo], query: str, mode: str) -> list[PackageInfo]:
    q = (query or "").strip().lower()
    result: list[PackageInfo] = []
    for info in packages:
        if q and q not in info.package.lower():
            continue
        if mode == "third" and info.system:
            continue
        if mode == "system" and not info.system:
            continue
        if mode == "disabled" and info.enabled:
            continue
        result.append(info)
    return result


class PackageService:
    def __init__(self, adb: AdbService) -> None:
        self.adb = adb

    @staticmethod
    def action_command(action: str, package: str) -> str:
        package = validate_package(package)
        try:
            template = _ACTION_COMMANDS[action]
        except KeyError as exc:
            raise ValueError(f"未知应用操作: {action}") from exc
        return template.format(package=package)

    def list_packages(self, serial: str) -> AdbProcess:
        return self.adb.shell(serial, _LIST_SCRIPT, timeout_ms=45000)

    def foreground(self, serial: str) -> AdbProcess:
        return self.adb.shell(serial, "dumpsys activity activities", timeout_ms=25000)

    def action(self, serial: str, action: str, package: str) -> AdbProcess:
        command = self.action_command(action, package)
        return self.adb.shell(serial, command, timeout_ms=60000 if action == "info" else 30000)

    @staticmethod
    def restart_command(package: str) -> str:
        return PackageService.action_command("restart", package)

    def restart(self, serial: str, package: str) -> AdbProcess:
        return self.adb.shell(
            serial,
            self.restart_command(package),
            timeout_ms=30000,
        )

    def extract_paths(self, serial: str, package: str) -> AdbProcess:
        return self.adb.shell(serial, self.action_command("path", package), timeout_ms=15000)

    @staticmethod
    def google_candidates(packages: list[PackageInfo], enable: bool) -> list[str]:
        result: list[str] = []
        for info in packages:
            if info.package not in GOOGLE_PACKAGES:
                continue
            if enable and not info.enabled:
                result.append(info.package)
            elif not enable and info.enabled:
                result.append(info.package)
        return result


class BatchPackageJob(QObject):
    item_finished = Signal(object)
    progress = Signal(int, int)
    finished = Signal(object)

    def __init__(
        self,
        service: PackageService,
        serial: str,
        action: str,
        packages: list[str],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.serial = serial
        self.action = action
        self.packages = [validate_package(package) for package in packages]
        self._index = 0
        self._results: list[BatchItemResult] = []
        self._current: AdbProcess | None = None
        self._cancelled = False

    def start(self) -> None:
        self._run_next()

    def cancel(self) -> None:
        self._cancelled = True
        if self._current is not None and self._current.is_running:
            self._current.cancel()

    def _run_next(self) -> None:
        if self._cancelled or self._index >= len(self.packages):
            self.finished.emit(list(self._results))
            return
        package = self.packages[self._index]
        self._current = self.service.action(self.serial, self.action, package)
        self._current.finished.connect(self._on_item_finished)

    def _on_item_finished(self, result) -> None:
        package = self.packages[self._index]
        item = BatchItemResult(
            package=package,
            ok=result.ok,
            output=(result.stdout or result.stderr).strip(),
        )
        self._results.append(item)
        self._index += 1
        self.item_finished.emit(item)
        self.progress.emit(self._index, len(self.packages))
        if self._cancelled:
            self.finished.emit(list(self._results))
            return
        QTimer.singleShot(0, self._run_next)


class ExtractApkJob(QObject):
    progress = Signal(int, int)
    item_finished = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        service: PackageService,
        serial: str,
        package: str,
        target_dir: Path,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.serial = serial
        self.package = validate_package(package)
        self.target_dir = Path(target_dir)
        self._paths: list[str] = []
        self._index = 0
        self._results: list[ExtractItemResult] = []
        self._current: AdbProcess | None = None
        self._cancelled = False
        self._finished_emitted = False
        self._pending_local: Path | None = None

    def start(self) -> None:
        try:
            self.target_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.failed.emit(f"无法创建目标目录: {exc}")
            return
        self._current = self.service.extract_paths(self.serial, self.package)
        self._current.finished.connect(self._on_paths)

    def cancel(self) -> None:
        self._cancelled = True
        if self._current is not None and self._current.is_running:
            self._current.cancel()
        if self._finished_emitted:
            return
        self._emit_finished()

    def _on_paths(self, result) -> None:
        if self._cancelled:
            self._emit_finished()
            return
        if not result.ok:
            self.failed.emit((result.stderr or result.stdout).strip() or "读取 APK 路径失败")
            return
        self._paths = parse_pm_path(result.stdout)
        if not self._paths:
            self.failed.emit("没有找到该应用的 APK 路径")
            return
        self._pull_next()

    def _local_path(self, remote: str) -> Path:
        basename = Path(remote).name or "package.apk"
        if basename == "base.apk":
            name = f"{self.package}.apk"
        else:
            name = f"{self.package}-{basename}"
        candidate = self.target_dir / name
        counter = 2
        while candidate.exists():
            candidate = self.target_dir / f"{candidate.stem}-{counter}{candidate.suffix}"
            counter += 1
        return candidate

    def _pull_next(self) -> None:
        if self._cancelled:
            self._emit_finished()
            return
        if self._index >= len(self._paths):
            self._emit_finished()
            return
        remote = self._paths[self._index]
        local = self._local_path(remote)
        self._pending_local = local
        self._current = self.service.adb.run_argv(
            self.service.adb.build(self.serial, "pull", remote, str(local)),
            timeout_ms=60000,
        )
        self._current.finished.connect(self._on_pull_finished)

    def _on_pull_finished(self, result) -> None:
        remote = self._paths[self._index]
        local = self._pending_local or self._local_path(remote)
        item = ExtractItemResult(
            remote=remote,
            local=str(local),
            ok=result.ok,
            output=(result.stdout or result.stderr).strip(),
            package=self.package,
        )
        self._results.append(item)
        self._index += 1
        self.item_finished.emit(item)
        self.progress.emit(self._index, len(self._paths))
        if self._cancelled:
            self._emit_finished()
            return
        QTimer.singleShot(0, self._pull_next)

    def _emit_finished(self) -> None:
        if self._finished_emitted:
            return
        self._finished_emitted = True
        self.finished.emit(list(self._results))


class BatchExtractJob(QObject):
    progress = Signal(int, int)
    item_finished = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        service: PackageService,
        serial: str,
        packages: list[str],
        target_dir: Path,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.serial = serial
        self.packages = [validate_package(package) for package in packages]
        self.target_dir = Path(target_dir)
        self._index = 0
        self._results: list[ExtractItemResult] = []
        self._current: ExtractApkJob | None = None
        self._cancelled = False
        self._finished_emitted = False

    def start(self) -> None:
        try:
            self.target_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.failed.emit(f"无法创建目标目录: {exc}")
            return
        probe = self.target_dir / ".adb-utils-write-test.tmp"
        try:
            probe.write_bytes(b"")
        except OSError as exc:
            self.failed.emit(f"目标目录不可写：{self.target_dir}（{exc}）")
            return
        try:
            probe.unlink()
        except OSError:
            pass
        self._run_next()

    def cancel(self) -> None:
        self._cancelled = True
        if self._current is not None:
            self._current.cancel()
        self._emit_finished()

    def _run_next(self) -> None:
        if self._cancelled or self._index >= len(self.packages):
            self._emit_finished()
            return
        package = self.packages[self._index]
        self.progress.emit(self._index, len(self.packages))
        job = ExtractApkJob(
            self.service,
            self.serial,
            package,
            self.target_dir,
            self,
        )
        self._current = job
        job.finished.connect(
            lambda items, p=package: self._on_package_finished(p, items)
        )
        job.failed.connect(
            lambda message, p=package: self._on_package_failed(p, message)
        )
        job.start()

    def _on_package_finished(self, package: str, items: list[ExtractItemResult]) -> None:
        if self._cancelled:
            self._emit_finished()
            return
        for item in items:
            self._results.append(item)
            self.item_finished.emit(item)
        self._advance()

    def _on_package_failed(self, package: str, message: str) -> None:
        if self._cancelled:
            self._emit_finished()
            return
        item = ExtractItemResult(
            remote="",
            local="",
            ok=False,
            output=message,
            package=package,
        )
        self._results.append(item)
        self.item_finished.emit(item)
        self._advance()

    def _advance(self) -> None:
        self._current = None
        self._index += 1
        self.progress.emit(min(self._index, len(self.packages)), len(self.packages))
        if self._cancelled or self._index >= len(self.packages):
            self._emit_finished()
            return
        QTimer.singleShot(0, self._run_next)

    def _emit_finished(self) -> None:
        if self._finished_emitted:
            return
        self._finished_emitted = True
        self.finished.emit(list(self._results))
