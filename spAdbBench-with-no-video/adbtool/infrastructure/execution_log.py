from __future__ import annotations

import json
import os
import subprocess
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .process import ProcessResult


def serial_from_argv(argv: list[str] | tuple[str, ...]) -> str:
    for index, value in enumerate(argv[:-1]):
        if value == "-s":
            return str(argv[index + 1])
    return ""


def format_command(argv: list[str] | tuple[str, ...]) -> str:
    return subprocess.list2cmdline([str(arg) for arg in argv])


@dataclass(frozen=True)
class ExecutionRecord:
    started_at: str
    serial: str
    command: str
    argv: tuple[str, ...]
    ok: bool
    exit_code: int
    duration_ms: int
    stdout: str
    stderr: str
    cancelled: bool = False
    timed_out: bool = False

    @property
    def result_text(self) -> str:
        if self.cancelled:
            return "已取消"
        if self.timed_out:
            return "超时"
        return "成功" if self.ok else "失败"

    @classmethod
    def from_process(
        cls,
        argv: list[str] | tuple[str, ...],
        result: ProcessResult,
        started_at: datetime,
        duration_ms: int,
    ) -> "ExecutionRecord":
        args = tuple(str(arg) for arg in argv)
        return cls(
            started_at=started_at.isoformat(timespec="seconds"),
            serial=serial_from_argv(args),
            command=format_command(args),
            argv=args,
            ok=result.ok,
            exit_code=result.exit_code,
            duration_ms=max(0, int(duration_ms)),
            stdout=result.stdout,
            stderr=result.stderr,
            cancelled=result.cancelled,
            timed_out=result.timed_out,
        )

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at,
            "serial": self.serial,
            "command": self.command,
            "argv": list(self.argv),
            "ok": self.ok,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "cancelled": self.cancelled,
            "timed_out": self.timed_out,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "ExecutionRecord":
        argv_raw = raw.get("argv", [])
        if not isinstance(argv_raw, list):
            raise ValueError("argv 不是列表")
        return cls(
            started_at=str(raw.get("started_at", "")),
            serial=str(raw.get("serial", "")),
            command=str(raw.get("command", "")),
            argv=tuple(str(arg) for arg in argv_raw),
            ok=bool(raw.get("ok", False)),
            exit_code=int(raw.get("exit_code", -1)),
            duration_ms=max(0, int(raw.get("duration_ms", 0))),
            stdout=str(raw.get("stdout", "")),
            stderr=str(raw.get("stderr", "")),
            cancelled=bool(raw.get("cancelled", False)),
            timed_out=bool(raw.get("timed_out", False)),
        )


class ExecutionLog(QObject):
    record_added = Signal(object)

    def __init__(
        self,
        path: Path | str | None = None,
        max_records: int = 2000,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.path = Path(path) if path is not None else None
        self._records: deque[ExecutionRecord] = deque(maxlen=max_records)
        self.last_error = ""
        if self.path is not None:
            self.reload()

    def records(self) -> list[ExecutionRecord]:
        return list(self._records)

    def add(self, record: ExecutionRecord) -> None:
        self._records.append(record)
        if self.path is not None:
            self._append_file(record)
        self.record_added.emit(record)

    def reload(self) -> None:
        self._records.clear()
        self.last_error = ""
        if self.path is None or not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = ExecutionRecord.from_dict(json.loads(line))
                    except (TypeError, ValueError, json.JSONDecodeError):
                        continue
                    self._records.append(record)
        except OSError as exc:
            self.last_error = str(exc)

    def clear_memory(self) -> None:
        self._records.clear()

    def flush(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            self.last_error = str(exc)

    def export(self, destination: Path | str) -> Path:
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            json.dumps(record.to_dict(), ensure_ascii=False)
            for record in self._records
        ]
        payload = "\n".join(lines)
        if payload:
            payload += "\n"
        target.write_text(payload, encoding="utf-8")
        return target

    def _append_file(self, record: ExecutionRecord) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(record.to_dict(), ensure_ascii=False) + "\n"
                )
        except OSError as exc:
            self.last_error = str(exc)
