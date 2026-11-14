from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_imports():
    import PySide6
    import wetest.scrcpy

    assert PySide6.__version__
    assert wetest.scrcpy.__name__ == "wetest.scrcpy"


def test_adb_and_scrcpy_server_exist():
    adb = ROOT / "platform-tools" / "adb.exe"
    server = ROOT / "vendor" / "scrcpy" / "scrcpy-server"

    assert adb.is_file()
    assert server.is_file()
    assert server.stat().st_size > 100_000
