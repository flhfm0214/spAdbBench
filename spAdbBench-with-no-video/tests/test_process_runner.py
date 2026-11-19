import sys
from pathlib import Path

from adbtool.infrastructure.process import AdbProcess
from adbtool.services.adb import AdbService


def test_process_success(qtbot):
    process = AdbProcess()
    with qtbot.waitSignal(process.finished, timeout=5000) as blocker:
        process.run([sys.executable, "-c", "print('ok')"])

    result = blocker.args[0]
    assert result.ok is True
    assert result.exit_code == 0
    assert "ok" in result.stdout


def test_process_nonzero_exit(qtbot):
    process = AdbProcess()
    with qtbot.waitSignal(process.finished, timeout=5000) as blocker:
        process.run([sys.executable, "-c", "import sys; sys.stderr.write('bad'); sys.exit(3)"])

    result = blocker.args[0]
    assert result.ok is False
    assert result.exit_code == 3
    assert "bad" in result.stderr


def test_process_timeout(qtbot):
    process = AdbProcess()
    with qtbot.waitSignal(process.finished, timeout=5000) as blocker:
        process.run([sys.executable, "-c", "import time; time.sleep(5)"], timeout_ms=300)

    result = blocker.args[0]
    assert result.timed_out is True
    assert result.ok is False


def test_process_cancel(qtbot):
    process = AdbProcess()
    with qtbot.waitSignal(process.finished, timeout=5000) as blocker:
        process.run([sys.executable, "-c", "import time; time.sleep(5)"])
        process.cancel()

    result = blocker.args[0]
    assert result.cancelled is True
    assert result.ok is False


def test_process_writes_binary_stdout_to_file(qtbot, tmp_path):
    destination = tmp_path / "screen.png"
    process = AdbProcess()
    with qtbot.waitSignal(process.finished, timeout=5000) as blocker:
        process.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.stdout.buffer.write(b'\\x89PNG\\r\\n\\x1a\\n')",
            ],
            stdout_file=destination,
        )

    result = blocker.args[0]
    assert result.ok is True
    assert destination.read_bytes() == b"\x89PNG\r\n\x1a\n"


def test_adb_service_writes_process_stdout_to_file(qtbot, tmp_path):
    destination = tmp_path / "screen.png"
    service = AdbService(Path("adb.exe"))
    process = service.run_argv_to_file(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(b'png-bytes')",
        ],
        destination,
    )
    qtbot.waitUntil(lambda: not process.is_running, timeout=5000)

    assert destination.read_bytes() == b"png-bytes"


def test_process_streams_without_retaining_output(qtbot):
    process = AdbProcess()
    chunks = []
    process.output.connect(chunks.append)
    with qtbot.waitSignal(process.finished, timeout=5000) as blocker:
        process.run(
            [sys.executable, "-c", "print('x' * 5000)"],
            capture_output=False,
        )

    result = blocker.args[0]
    assert result.stdout == ""
    assert "".join(chunks).strip() == "x" * 5000


def test_adb_service_releases_finished_process(qtbot):
    import gc
    import weakref

    service = AdbService(Path("adb.exe"))
    first = service.run_argv(
        [sys.executable, "-c", "print('ok')"],
        record=False,
    )
    # Mirrors callers that capture the process to identify the sender.
    first.finished.connect(lambda result, p=first: None)
    first_ref = weakref.ref(first)
    qtbot.waitUntil(lambda: not first.is_running, timeout=5000)
    del first

    for _ in range(39):
        process = service.run_argv(
            [sys.executable, "-c", "print('ok')"],
            record=False,
        )
        qtbot.waitUntil(lambda p=process: not p.is_running, timeout=5000)

    qtbot.wait(50)
    gc.collect()
    assert service.findChildren(AdbProcess) == []
    assert len(service._retired) == 32
    assert first_ref() is None


