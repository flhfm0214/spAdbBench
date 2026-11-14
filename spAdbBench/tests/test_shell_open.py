from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl

from adbtool.infrastructure.shell_open import open_folder


def test_windows_opens_folder_through_explorer(tmp_path):
    calls = []

    def start_detached(program, args):
        calls.append((program, args))
        return True, 1234

    assert open_folder(
        tmp_path,
        platform="win32",
        start_detached=start_detached,
    ) is True
    assert calls == [("explorer.exe", [str(tmp_path.resolve())])]


def test_windows_reports_explorer_failure(tmp_path):
    assert open_folder(
        tmp_path,
        platform="win32",
        start_detached=lambda _program, _args: (False, 0),
    ) is False


def test_missing_folder_is_not_opened(tmp_path):
    calls = []
    missing = tmp_path / "missing"

    assert open_folder(
        missing,
        platform="win32",
        start_detached=lambda *args: calls.append(args) or True,
    ) is False
    assert calls == []


def test_non_windows_uses_desktop_services(tmp_path):
    calls = []

    def open_url(url):
        calls.append(url.toString())
        return True

    assert open_folder(
        tmp_path,
        platform="linux",
        open_url=open_url,
    ) is True
    assert calls
    assert Path(QUrl(calls[0]).toLocalFile()) == tmp_path.resolve()
