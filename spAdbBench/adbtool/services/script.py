from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtCore import QProcess


MAX_STEPS = 2000
MAX_TIMEOUT_S = 300
DEFAULT_ADB_TIMEOUT_S = 60


@dataclass(frozen=True)
class ScriptExecResult:
    ok: bool
    output: str = ""
    error: str = ""


@dataclass(frozen=True)
class ScriptLineResult:
    line_no: int
    kind: str
    text: str
    ok: bool = True
    output: str = ""


@dataclass
class ScriptRunResult:
    exit_code: int
    cancelled: bool = False
    error: str = ""
    executed_commands: list[str] = field(default_factory=list)


def _no_executor(command: str, timeout: int) -> ScriptExecResult:
    return ScriptExecResult(False, "", "脚本没有配置 ADB 执行器")


def _split_command(command: str) -> list[str]:
    tokens: list[str] = []
    current: list[str] = []
    quote = ""
    for char in command:
        if quote:
            if char == quote:
                quote = ""
            else:
                current.append(char)
        elif char in {"'", '"'}:
            quote = char
        elif char.isspace():
            if current:
                tokens.append("".join(current))
                current = []
        else:
            current.append(char)
    if current:
        tokens.append("".join(current))
    return tokens


class ScriptInterpreter:
    def __init__(
        self,
        executor: Callable[[str, int], ScriptExecResult] | None = None,
        *,
        max_steps: int = MAX_STEPS,
        max_timeout_s: int = MAX_TIMEOUT_S,
        cancel_event=None,
        wait: Callable[[float], object] | None = None,
    ) -> None:
        self.executor = executor or _no_executor
        self.max_steps = max_steps
        self.max_timeout_s = max_timeout_s
        self.cancel_event = cancel_event or threading.Event()
        self._wait = wait or self.cancel_event.wait
        self._variables: dict[str, str] = {}

    def run(
        self,
        source: str,
        on_line: Callable[[ScriptLineResult], None] | None = None,
    ) -> ScriptRunResult:
        emit = on_line or (lambda _item: None)
        lines = (source or "").splitlines()
        labels = self._collect_labels(lines)
        executed: list[str] = []
        had_failure = False
        pc = 0
        steps = 0

        while pc < len(lines):
            if self.cancel_event.is_set():
                return ScriptRunResult(1, True, "脚本已取消", executed)
            raw = lines[pc]
            pc += 1
            line = raw.strip()
            if not line:
                continue
            steps += 1
            if steps > self.max_steps:
                return ScriptRunResult(
                    1,
                    False,
                    f"脚本执行步数超过上限 {self.max_steps}，可能存在死循环",
                    executed,
                )

            low = line.lower()
            if low in {"@echo off", "echo off", "echo on", "@echo on"}:
                continue
            if line.startswith("::") or low == "rem" or low.startswith("rem "):
                continue
            if line.startswith(":") and not line.startswith("::"):
                continue

            if low == "echo":
                emit(ScriptLineResult(steps, "echo", ""))
                continue
            if low == "echo.":
                emit(ScriptLineResult(steps, "echo", ""))
                continue
            if low.startswith("echo "):
                emit(
                    ScriptLineResult(
                        steps,
                        "echo",
                        self._expand(line[5:].strip()),
                    )
                )
                continue

            if low.startswith("set "):
                payload = line[4:].strip()
                if "=" not in payload:
                    emit(
                        ScriptLineResult(
                            steps,
                            "unsupported",
                            line,
                            False,
                            "set 只支持 NAME=value 形式",
                        )
                    )
                    had_failure = True
                    continue
                name, value = payload.split("=", 1)
                name = name.strip()
                if not name:
                    emit(
                        ScriptLineResult(
                            steps,
                            "unsupported",
                            line,
                            False,
                            "变量名不能为空",
                        )
                    )
                    had_failure = True
                    continue
                self._variables[name.lower()] = self._expand(value)
                continue

            if low.startswith("goto "):
                target = self._expand(line[5:].strip()).lower()
                if target not in labels:
                    return ScriptRunResult(
                        1,
                        False,
                        f"找不到标签: {target}",
                        executed,
                    )
                pc = labels[target] + 1
                continue

            if low.startswith("timeout "):
                seconds, error = self._parse_wait(line, "timeout")
                if error:
                    return ScriptRunResult(1, False, error, executed)
                emit(
                    ScriptLineResult(
                        steps,
                        "info",
                        f"等待 {seconds:g} 秒",
                    )
                )
                self._wait(seconds)
                if self.cancel_event.is_set():
                    return ScriptRunResult(1, True, "脚本已取消", executed)
                continue

            if low.startswith("choice "):
                seconds, error = self._parse_wait(line, "choice")
                if error:
                    return ScriptRunResult(1, False, error, executed)
                emit(
                    ScriptLineResult(
                        steps,
                        "info",
                        f"choice 等待 {seconds:g} 秒，继续执行",
                    )
                )
                self._wait(seconds)
                if self.cancel_event.is_set():
                    return ScriptRunResult(1, True, "脚本已取消", executed)
                continue

            if low == "pause":
                emit(
                    ScriptLineResult(
                        steps,
                        "info",
                        "pause：非交互运行，已跳过",
                    )
                )
                continue

            if low.startswith("exit"):
                return ScriptRunResult(
                    self._parse_exit_code(line),
                    False,
                    "",
                    executed,
                )

            if low.startswith("@"):
                low = low[1:]
                line = line[1:].lstrip()
            if low == "adb" or low.startswith("adb "):
                command = line[4:].strip()
                if not command:
                    emit(
                        ScriptLineResult(
                            steps,
                            "unsupported",
                            line,
                            False,
                            "adb 后没有命令",
                        )
                    )
                    had_failure = True
                    continue
                command = self._expand(command)
                result = self.executor(command, DEFAULT_ADB_TIMEOUT_S)
                output = result.output or result.error
                if not result.ok:
                    had_failure = True
                executed.append(command)
                emit(
                    ScriptLineResult(
                        steps,
                        "command",
                        command,
                        result.ok,
                        output,
                    )
                )
                if self.cancel_event.is_set():
                    return ScriptRunResult(1, True, "脚本已取消", executed)
                continue

            emit(
                ScriptLineResult(
                    steps,
                    "unsupported",
                    line,
                    False,
                    "不支持的本地命令，未执行",
                )
            )
            had_failure = True

        if self.cancel_event.is_set():
            return ScriptRunResult(1, True, "脚本已取消", executed)
        return ScriptRunResult(1 if had_failure else 0, False, "", executed)

    @staticmethod
    def _collect_labels(lines: list[str]) -> dict[str, int]:
        labels: dict[str, int] = {}
        for index, raw in enumerate(lines):
            line = raw.strip()
            if line.startswith(":") and not line.startswith("::"):
                name = line[1:].strip().lower()
                if name:
                    labels[name] = index
        return labels

    def _expand(self, text: str) -> str:
        def replace(match: re.Match[str]) -> str:
            name = match.group(1).lower()
            return self._variables.get(name, match.group(0))

        return re.sub(r"%([^%]+)%", replace, text)

    def _parse_wait(self, line: str, kind: str) -> tuple[float, str]:
        match = re.search(r"/t\s+(\d+)", line, re.IGNORECASE)
        if not match:
            return 0, f"{kind} 缺少 /t 秒数"
        seconds = int(match.group(1))
        if seconds > self.max_timeout_s:
            return 0, f"{kind} 等待时间不能超过 {self.max_timeout_s} 秒"
        return float(seconds), ""

    @staticmethod
    def _parse_exit_code(line: str) -> int:
        match = re.search(r"(?:/b\s+)?(-?\d+)\s*$", line, re.IGNORECASE)
        if not match:
            return 0
        try:
            return max(0, min(255, int(match.group(1))))
        except ValueError:
            return 0


def run_script(
    source: str,
    on_line: Callable[[ScriptLineResult], None] | None = None,
    *,
    executor: Callable[[str, int], ScriptExecResult] | None = None,
    wait: Callable[[float], object] | None = None,
    cancel_event=None,
) -> ScriptRunResult:
    return ScriptInterpreter(
        executor,
        wait=wait,
        cancel_event=cancel_event,
    ).run(source, on_line)


class ScriptWorker(QObject):
    line = Signal(object)
    finished = Signal(object)

    def __init__(self, adb_path: str, serial: str, source: str) -> None:
        super().__init__()
        self.adb_path = str(adb_path)
        self.serial = serial
        self.source = source
        self._cancel = threading.Event()
        self._process: QProcess | None = None

    def request_cancel(self) -> None:
        self._cancel.set()

    @Slot()
    def run(self) -> None:
        interpreter = ScriptInterpreter(
            executor=self._execute,
            cancel_event=self._cancel,
        )
        result = interpreter.run(self.source, self.line.emit)
        self.finished.emit(result)

    def _argument_vector(self, command: str) -> list[str]:
        argv = [self.adb_path]
        if self.serial:
            argv.extend(["-s", self.serial])
        if command.lower() == "shell" or command.lower().startswith("shell "):
            script = command[5:].strip()
            argv.extend(["shell", script])
            return argv
        argv.extend(_split_command(command))
        return argv

    def _execute(self, command: str, timeout_s: int) -> ScriptExecResult:
        argv = self._argument_vector(command)
        if len(argv) <= (1 if not self.serial else 3):
            return ScriptExecResult(False, "", "命令为空")
        process = QProcess()
        self._process = process
        process.setProgram(argv[0])
        process.setArguments(argv[1:])
        process.start()
        if not process.waitForStarted(5000):
            self._process = None
            return ScriptExecResult(False, "", "ADB 进程启动失败")

        deadline = time.monotonic() + timeout_s
        while process.state() != QProcess.NotRunning:
            if self._cancel.is_set():
                process.kill()
                process.waitForFinished(1000)
                self._process = None
                return ScriptExecResult(False, "", "脚本已取消")
            if time.monotonic() >= deadline:
                process.kill()
                process.waitForFinished(1000)
                self._process = None
                return ScriptExecResult(False, "", f"命令超过 {timeout_s} 秒")
            process.waitForFinished(100)

        stdout = bytes(process.readAllStandardOutput()).decode("utf-8", "replace")
        stderr = bytes(process.readAllStandardError()).decode("utf-8", "replace")
        ok = process.exitStatus() == QProcess.NormalExit and process.exitCode() == 0
        self._process = None
        return ScriptExecResult(ok, stdout, stderr)


class ScriptJob(QObject):
    line = Signal(object)
    finished = Signal(object)
    state = Signal(str)

    def __init__(
        self,
        adb_path: str,
        serial: str,
        source: str,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._thread = QThread(self)
        self._worker = ScriptWorker(adb_path, serial, source)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.line.connect(self.line)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._thread.quit)
        self._result = None
        self._started = False

    @property
    def is_running(self) -> bool:
        return self._started and self._thread.isRunning()

    def start(self) -> None:
        if self.is_running:
            return
        self._started = True
        self.state.emit("运行中")
        self._thread.start()

    def cancel(self) -> None:
        if not self.is_running:
            return
        self.state.emit("正在停止")
        self._worker.request_cancel()

    def wait(self, timeout_ms: int = 2000) -> None:
        self._thread.wait(timeout_ms)

    def _on_finished(self, result: ScriptRunResult) -> None:
        self._result = result
        if result.cancelled:
            self.state.emit("已停止")
        elif result.exit_code == 0:
            self.state.emit("已完成")
        else:
            self.state.emit("执行失败")
        self.finished.emit(result)
