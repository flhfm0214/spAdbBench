from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from adbtool.infrastructure.process import ProcessResult
from adbtool.services.packages import BatchExtractJob


class FakeProcess(QObject):
    finished = Signal(object)

    def __init__(self, result: ProcessResult, action=None, parent=None) -> None:
        super().__init__(parent)
        self._result = result
        self._action = action
        self.is_running = True
        QTimer.singleShot(0, self._finish)

    def _finish(self) -> None:
        self.is_running = False
        if self._action is not None:
            self._action()
        self.finished.emit(self._result)

    def cancel(self) -> None:
        self.is_running = False


class FakeExtractService:
    def __init__(self, paths_by_package: dict[str, list[str]]) -> None:
        self.paths_by_package = paths_by_package
        self.adb = self
        self.pulled: list[list[str]] = []

    def extract_paths(self, serial: str, package: str):
        paths = self.paths_by_package.get(package, [])
        output = "".join(f"package:{path}\n" for path in paths)
        return FakeProcess(ProcessResult(True, 0, output, ""))

    def build(self, serial: str, *args: str) -> list[str]:
        return ["adb", "-s", serial, *args]

    def run_argv(self, argv: list[str], timeout_ms: int = 30000):
        self.pulled.append(argv)
        local = Path(argv[-1])

        def write_file() -> None:
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(b"apk")

        return FakeProcess(ProcessResult(True, 0, "1 file pulled", ""), write_file)


def test_batch_extract_exports_all_selected_packages(qtbot, tmp_path):
    service = FakeExtractService(
        {
            "com.example.one": [
                "/data/app/com.example.one/base.apk",
                "/data/app/com.example.one/split_config.arm64_v8a.apk",
            ],
            "com.example.two": ["/data/app/com.example.two/base.apk"],
        }
    )
    job = BatchExtractJob(
        service,
        "ABC",
        ["com.example.one", "com.example.two"],
        tmp_path,
    )
    results: list[object] = []
    job.finished.connect(results.append)

    job.start()

    qtbot.waitUntil(lambda: bool(results), timeout=5000)
    items = results[0]
    assert len(items) == 3
    assert {item.package for item in items} == {
        "com.example.one",
        "com.example.two",
    }
    assert all(item.ok for item in items)
    assert (tmp_path / "com.example.one.apk").read_bytes() == b"apk"
    assert (tmp_path / "com.example.one-split_config.arm64_v8a.apk").exists()
    assert (tmp_path / "com.example.two.apk").read_bytes() == b"apk"


def test_batch_extract_continues_after_one_package_fails(qtbot, tmp_path):
    service = FakeExtractService(
        {
            "com.example.bad": [],
            "com.example.good": ["/data/app/com.example.good/base.apk"],
        }
    )
    job = BatchExtractJob(
        service,
        "ABC",
        ["com.example.bad", "com.example.good"],
        tmp_path,
    )
    results: list[object] = []
    job.finished.connect(results.append)

    job.start()

    qtbot.waitUntil(lambda: bool(results), timeout=5000)
    items = results[0]
    assert [item.package for item in items] == [
        "com.example.bad",
        "com.example.good",
    ]
    assert items[0].ok is False
    assert "没有找到" in items[0].output
    assert items[1].ok is True
    assert (tmp_path / "com.example.good.apk").exists()


def test_batch_extract_reports_unwritable_target_before_pulling(
    qtbot, tmp_path, monkeypatch
):
    service = FakeExtractService(
        {"com.example.one": ["/data/app/com.example.one/base.apk"]}
    )
    job = BatchExtractJob(
        service,
        "ABC",
        ["com.example.one"],
        tmp_path,
    )
    failures: list[str] = []
    job.failed.connect(failures.append)

    def deny_write(self, data):
        raise PermissionError("access denied")

    monkeypatch.setattr(Path, "write_bytes", deny_write)
    job.start()

    assert failures
    assert "目标目录不可写" in failures[0]
    assert service.pulled == []

