from __future__ import annotations

import threading

from adbtool.services.script import (
    ScriptExecResult,
    ScriptInterpreter,
    run_script,
)


def test_set_goto_and_echo():
    out = []
    script = (
        "@echo off\n"
        "set X=hello\n"
        "echo %X%\n"
        "goto done\n"
        "echo NO\n"
        ":done\n"
        "echo END\n"
    )

    result = run_script(script, on_line=out.append)

    assert [item.text for item in out if item.kind == "echo"] == ["hello", "END"]
    assert result.exit_code == 0


def test_unsupported_line_is_reported_not_executed():
    out = []
    result = run_script("del /q C:\\Windows\\*.*\n", on_line=out.append)

    assert out[0].kind == "unsupported"
    assert result.executed_commands == []
    assert result.exit_code != 0


def test_goto_missing_label_stops():
    result = run_script("goto nowhere\n", on_line=lambda _: None)

    assert result.exit_code != 0
    assert "找不到标签" in result.error


def test_timeout_is_cancellable_without_real_sleep():
    calls = []

    result = run_script(
        "timeout /t 2\n",
        on_line=lambda _: None,
        wait=lambda seconds: calls.append(seconds),
    )

    assert calls == [2]
    assert result.exit_code == 0


def test_cancel_event_stops_before_next_command():
    event = threading.Event()
    event.set()
    calls = []

    result = run_script(
        "adb shell echo hi\n",
        on_line=lambda _: None,
        executor=lambda command, timeout: calls.append(command)
        or ScriptExecResult(True, "", ""),
        cancel_event=event,
    )

    assert result.cancelled is True
    assert calls == []


def test_adb_commands_are_executed_without_prefix():
    calls = []

    def executor(command, timeout):
        calls.append((command, timeout))
        return ScriptExecResult(True, "ok", "")

    script = "adb shell echo hi\nadb devices\n"
    out = []
    result = run_script(script, on_line=out.append, executor=executor)

    assert calls[0][0] == "shell echo hi"
    assert calls[1][0] == "devices"
    assert result.executed_commands == ["shell echo hi", "devices"]
    assert result.exit_code == 0
    assert [item.kind for item in out] == ["command", "command"]


def test_failed_adb_command_is_reported_and_script_continues():
    results = iter(
        [
            ScriptExecResult(False, "", "not found"),
            ScriptExecResult(True, "done", ""),
        ]
    )
    out = []

    result = run_script(
        "adb shell false\nadb shell true\n",
        on_line=out.append,
        executor=lambda command, timeout: next(results),
    )

    assert len(result.executed_commands) == 2
    assert out[0].ok is False
    assert "not found" in out[0].output
    assert out[1].ok is True
    assert result.exit_code == 1


def test_exit_b_sets_exit_code():
    result = run_script("exit /b 3\n", on_line=lambda _: None)

    assert result.exit_code == 3


def test_loop_limit_is_reported():
    result = run_script(":loop\ngoto loop\n", on_line=lambda _: None)

    assert result.exit_code != 0
    assert "步数" in result.error


def test_at_prefixed_adb_command_is_supported():
    calls = []

    result = run_script(
        "@adb devices\n",
        on_line=lambda _: None,
        executor=lambda command, timeout: calls.append(command)
        or ScriptExecResult(True, "", ""),
    )

    assert calls == ["devices"]
    assert result.executed_commands == ["devices"]


def test_undefined_variable_is_left_unchanged():
    out = []
    run_script("echo %MISSING%\n", on_line=out.append)

    assert out[0].text == "%MISSING%"


def test_timeout_above_limit_is_rejected():
    result = run_script("timeout /t 301\n", on_line=lambda _: None)

    assert result.exit_code != 0
    assert "300" in result.error
