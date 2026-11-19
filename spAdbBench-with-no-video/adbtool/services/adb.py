from __future__ import annotations

from collections import deque
from datetime import datetime
from pathlib import Path
from time import perf_counter

from PySide6.QtCore import QObject

from ..infrastructure.execution_log import ExecutionLog, ExecutionRecord
from ..infrastructure.process import AdbProcess


class AdbService(QObject):
    def __init__(
        self,
        adb_path: Path | str,
        parent: QObject | None = None,
        execution_log: ExecutionLog | None = None,
    ) -> None:
        super().__init__(parent)
        self.adb_path = Path(adb_path)
        self.execution_log = execution_log or ExecutionLog()
        self._active: set[AdbProcess] = set()
        self._meta: dict[AdbProcess, tuple] = {}
        # Finished wrappers are kept briefly so a caller that still holds a
        # reference never touches an already-deleted QObject.  The bounded
        # deque lets old wrappers be collected outside their finish callback.
        self._retired: deque[AdbProcess] = deque(maxlen=32)

    def build(self, serial: str | None, *args: str) -> list[str]:
        argv = [str(self.adb_path)]
        if serial:
            argv.extend(["-s", serial])
        argv.extend(str(arg) for arg in args)
        return argv

    def shell_argv(self, serial: str, script: str) -> list[str]:
        return self.build(serial, "shell", script)

    def run(
        self,
        serial: str | None,
        *args: str,
        timeout_ms: int = 30000,
        record: bool = True,
        capture_output: bool = True,
    ) -> AdbProcess:
        return self.run_argv(
            self.build(serial, *args),
            timeout_ms=timeout_ms,
            record=record,
            capture_output=capture_output,
        )

    def shell(
        self,
        serial: str,
        script: str,
        timeout_ms: int = 30000,
        record: bool = True,
        capture_output: bool = True,
    ) -> AdbProcess:
        return self.run_argv(
            self.shell_argv(serial, script),
            timeout_ms=timeout_ms,
            record=record,
            capture_output=capture_output,
        )

    def run_argv(
        self,
        argv: list[str],
        timeout_ms: int = 30000,
        record: bool = True,
        capture_output: bool = True,
    ) -> AdbProcess:
        process = self._new_process(argv, record=record)
        process.run(
            argv,
            timeout_ms=timeout_ms,
            capture_output=capture_output,
        )
        return process

    def run_argv_to_file(
        self,
        argv: list[str],
        output_path: Path | str,
        timeout_ms: int = 30000,
        record: bool = True,
    ) -> AdbProcess:
        process = self._new_process(argv, record=record)
        process.run(argv, timeout_ms=timeout_ms, stdout_file=output_path)
        return process

    def _new_process(self, argv: list[str], record: bool = True) -> AdbProcess:
        # No parent: a QObject parent would keep every finished command alive
        # for the whole application lifetime.  _active owns running processes;
        # _retired keeps a short, bounded tail for callers' safety.
        process = AdbProcess()
        self._active.add(process)
        self._meta[process] = (
            tuple(argv),
            datetime.now().astimezone(),
            perf_counter(),
            record,
        )
        process.completed.connect(self._on_completed)
        return process

    def _on_completed(self, process: AdbProcess, result) -> None:
        self._active.discard(process)
        self._retired.append(process)
        meta = self._meta.pop(process, None)
        if meta is None:
            return
        argv, started_at, started, record = meta
        if not record:
            return
        duration_ms = int((perf_counter() - started) * 1000)
        self.execution_log.add(
            ExecutionRecord.from_process(
                argv,
                result,
                started_at,
                duration_ms,
            )
        )

    def shutdown(self) -> None:
        for process in list(self._active):
            process.cancel()
            process.wait(1000)
        self._active.clear()
        self._meta.clear()
        self._retired.clear()
