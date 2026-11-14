from __future__ import annotations

from dataclasses import asdict, fields
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from ..channels.scrcpy_session import ScrcpySession
from ..infrastructure.adb_locator import AdbNotFoundError, resolve_adb
from ..infrastructure.config import AppConfig, ConfigStore
from ..infrastructure.parsers import DeviceInfo
from ..services.adb import AdbService
from ..services.battery_state import BatterySimulationTracker
from ..services.devices import DeviceService
from ..services.metrics import MetricsMonitor, clamp_interval
from ..services.settings_history import SettingsHistoryStore
from ..services.snapshot import SnapshotService
from ..services.snapshot_registry import SNAPSHOT_FIELDS
from .status_bus import StatusBus


class AppContext(QObject):
    device_changed = Signal(object)
    devices_changed = Signal(object)
    device_selected = Signal(object)
    metrics_interval_changed = Signal(int)
    config_changed = Signal()
    fastboot_devices_changed = Signal(object)
    device_visibility_changed = Signal()

    def __init__(
        self,
        config: AppConfig,
        config_store: ConfigStore,
        adb: AdbService,
        device_service: DeviceService,
        status: StatusBus,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.config_store = config_store
        self.adb = adb
        self.execution_log = adb.execution_log
        self.device_service = device_service
        self.metrics = MetricsMonitor(adb, config.metrics_interval_ms, self)
        self.scrcpy = ScrcpySession(config, adb, self, max_fps=config.preview_fps)
        self.settings_history = SettingsHistoryStore(
            config_store.root / "data" / "settings_history.json"
        )
        self.battery_tracker = BatterySimulationTracker(
            config_store.root / "data" / "battery_simulation.json"
        )
        self.snapshots = SnapshotService(
            adb,
            SNAPSHOT_FIELDS,
            self.settings_history,
            self.battery_tracker,
        )
        self.status = status
        self.current_device: DeviceInfo | None = None
        self.devices: list[DeviceInfo] = []
        self.fastboot_devices: list = []
        self.hidden_serials: set[str] = set()
        self.disconnected_serials: set[str] = set()
        self._show_hidden_on_refresh = False

    @property
    def completion_config_dir(self) -> Path:
        return self.config_store.root / "config" / "completions"

    def select_device(self, device: DeviceInfo | None) -> None:
        self.device_selected.emit(device)

    def set_current_device(self, device: DeviceInfo | None) -> None:
        self.current_device = device
        self.device_changed.emit(device)

    def set_devices(self, devices: list[DeviceInfo]) -> None:
        self.devices = list(devices)
        self.devices_changed.emit(self.devices)

    def set_fastboot_devices(self, devices) -> None:
        self.fastboot_devices = list(devices)
        self.fastboot_devices_changed.emit(self.fastboot_devices)

    def is_device_hidden(self, serial: str) -> bool:
        return bool(serial) and serial in self.hidden_serials

    def hide_device(self, serial: str) -> None:
        serial = (serial or "").strip()
        if not serial:
            return
        self.hidden_serials.add(serial)
        self.device_visibility_changed.emit()

    def clear_hidden_devices(self) -> None:
        if not self.hidden_serials:
            return
        self.hidden_serials.clear()
        self.device_visibility_changed.emit()

    def is_device_disconnected(self, serial: str) -> bool:
        return bool(serial) and serial in self.disconnected_serials

    @staticmethod
    def is_usb_serial(serial: str) -> bool:
        serial = (serial or "").strip()
        if not serial:
            return False
        # ADB wireless serials contain a host:port, mDNS name, or TLS marker.
        return not (
            ":" in serial
            or serial.startswith("adb-tls")
            or "._adb" in serial
            or "_adb-tls" in serial
        )

    def disconnect_device(self, serial: str) -> None:
        serial = (serial or "").strip()
        if not serial:
            return
        self.disconnected_serials.add(serial)
        self.device_visibility_changed.emit()

    def reconnect_device(self, serial: str) -> None:
        serial = (serial or "").strip()
        if serial and serial in self.disconnected_serials:
            self.disconnected_serials.discard(serial)
            self.device_visibility_changed.emit()

    def reconnect_usb_devices(self, devices: list[DeviceInfo]) -> bool:
        usb_serials = {
            device.serial
            for device in devices
            if self.is_usb_serial(device.serial)
        }
        before = len(self.disconnected_serials)
        self.disconnected_serials.difference_update(usb_serials)
        return len(self.disconnected_serials) != before

    def request_show_hidden_on_refresh(self) -> None:
        self._show_hidden_on_refresh = True

    def consume_show_hidden_on_refresh(
        self,
        active_serials: set[str] | None = None,
    ) -> bool:
        pending = self._show_hidden_on_refresh
        self._show_hidden_on_refresh = False
        if pending:
            if active_serials is None:
                self.hidden_serials.clear()
            else:
                # A deleted device comes back only when it is actually online
                # again. Stale offline entries stay hidden after a refresh.
                self.hidden_serials.difference_update(active_serials)
        return pending

    def cancel_show_hidden_on_refresh(self) -> None:
        self._show_hidden_on_refresh = False

    def set_metrics_interval(self, interval_ms: int) -> None:
        interval = clamp_interval(interval_ms)
        self.config.metrics_interval_ms = interval
        self.config_store.save(self.config)
        self.metrics.set_interval(interval)
        self.metrics_interval_changed.emit(interval)

    def apply_config(self, changes: dict) -> None:
        """Persist and apply application settings without rebuilding services."""
        if not isinstance(changes, dict):
            raise TypeError("changes must be a dict")
        known = {f.name for f in fields(AppConfig)}
        old = asdict(self.config)
        for key, value in changes.items():
            if key in known:
                setattr(self.config, key, value)

        normalized = AppConfig.from_dict(asdict(self.config))
        self.config.__dict__.update(normalized.__dict__)
        self.config_store.save(self.config)

        resolved_changes = {
            key: (old.get(key), getattr(self.config, key))
            for key in known
            if old.get(key) != getattr(self.config, key)
        }

        if "adb_path" in resolved_changes:
            try:
                self.adb.adb_path = resolve_adb(self.config, self.config_store.root)
            except AdbNotFoundError:
                self.adb.adb_path = Path(self.config.adb_path or "adb")
                self.status.error("未找到新的 ADB 路径，请检查设置")
            else:
                self.status.info(f"ADB 路径已更新：{self.adb.adb_path}")

        if "metrics_interval_ms" in resolved_changes:
            self.metrics.set_interval(self.config.metrics_interval_ms)
            self.metrics_interval_changed.emit(self.config.metrics_interval_ms)

        preview_keys = {
            "preview_fps",
            "scrcpy_max_size",
            "scrcpy_max_fps",
            "scrcpy_bit_rate",
            "scrcpy_server_path",
        }
        if preview_keys & set(resolved_changes):
            self.scrcpy.max_fps = self.config.preview_fps
            session = self.scrcpy
            if session.serial and session.state in {
                "启动服务",
                "等待控制连接",
                "等待视频",
                "已连接",
            }:
                session.start(session.serial)

        self.config_changed.emit()

    def set_preview_fps(self, fps: int) -> None:
        self.apply_config({"preview_fps": fps})

    def shutdown(self) -> None:
        self.metrics.stop()
        self.scrcpy.stop()
        self.adb.shutdown()
        self.execution_log.flush()
