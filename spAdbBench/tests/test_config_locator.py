from pathlib import Path

import pytest

from adbtool.infrastructure.adb_locator import AdbNotFoundError, resolve_adb
from adbtool.infrastructure.config import AppConfig, ConfigStore


def test_adb_prefers_existing_configured_path(tmp_path):
    adb = tmp_path / "custom" / "adb.exe"
    adb.parent.mkdir()
    adb.write_bytes(b"x")
    cfg = AppConfig(adb_path=str(adb))

    assert resolve_adb(cfg, project_root=tmp_path, which=lambda _: None) == adb


def test_adb_falls_back_to_bundled_then_path(tmp_path):
    bundled = tmp_path / "platform-tools" / "adb.exe"
    bundled.parent.mkdir()
    bundled.write_bytes(b"x")
    cfg = AppConfig(adb_path="")

    assert resolve_adb(cfg, project_root=tmp_path, which=lambda _: None) == bundled

    bundled.unlink()
    path_adb = tmp_path / "path-adb.exe"
    path_adb.write_bytes(b"x")
    assert resolve_adb(cfg, project_root=tmp_path, which=lambda _: str(path_adb)) == path_adb


def test_adb_raises_when_nothing_found(tmp_path):
    with pytest.raises(AdbNotFoundError):
        resolve_adb(AppConfig(adb_path=""), project_root=tmp_path, which=lambda _: None)


def test_config_roundtrip_and_defaults(tmp_path):
    store = ConfigStore(tmp_path)
    config = AppConfig(adb_path="A", metrics_interval_ms=3000, theme="dark")

    store.save(config)

    loaded = store.load()
    assert loaded.adb_path == "A"
    assert loaded.metrics_interval_ms == 3000
    assert loaded.theme == "dark"
    assert loaded.scrcpy_max_fps == 30

    config.metrics_interval_ms = 0
    store.save(config)
    assert store.load().metrics_interval_ms == 0


def test_config_clamps_metrics_interval_to_100ms(tmp_path):
    store = ConfigStore(tmp_path)
    store.save(AppConfig(metrics_interval_ms=50))

    assert store.load().metrics_interval_ms == 100


def test_config_corrupt_file_falls_back_to_defaults(tmp_path):
    store = ConfigStore(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("{broken", encoding="utf-8")

    loaded = store.load()
    assert loaded.metrics_interval_ms == 1000
    assert loaded.device_poll_ms == 1000
    assert loaded.theme == "dark"
