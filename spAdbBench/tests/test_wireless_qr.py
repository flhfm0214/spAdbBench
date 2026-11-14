from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QObject, Qt, Signal

from adbtool.infrastructure.config import AppConfig, ConfigStore
from adbtool.infrastructure.parsers import DeviceInfo
from adbtool.services.adb import AdbService
from adbtool.services.devices import DeviceService
from adbtool.services.wireless import (
    CONNECT_SERVICE,
    PAIRING_SERVICE,
    find_service,
    make_pairing_credentials,
    parse_mdns_services,
)
from adbtool.ui.context import AppContext
from adbtool.ui.pages.device_page import DevicePage
from adbtool.ui.status_bus import StatusBus
from adbtool.ui.widgets.wireless_qr import WirelessQrDialog, make_qr_pixmap


def make_context(tmp_path):
    config = AppConfig(adb_path=str(Path("platform-tools") / "adb.exe"))
    adb = AdbService(Path(config.adb_path))
    return AppContext(
        config,
        ConfigStore(tmp_path),
        adb,
        DeviceService(adb),
        StatusBus(),
    )


def test_parse_mdns_services_finds_pairing_and_connect():
    output = (
        "List of discovered mdns services\n"
        "adb-ABC\t_adb-tls-pairing._tcp\t192.168.1.5:37123\n"
        "adb-ABC\t_adb-tls-connect._tcp\t192.168.1.5:42351\n"
    )

    services = parse_mdns_services(output)

    assert [service.address for service in services] == [
        "192.168.1.5:37123",
        "192.168.1.5:42351",
    ]
    assert find_service(services, PAIRING_SERVICE).address == "192.168.1.5:37123"
    assert find_service(services, CONNECT_SERVICE).address == "192.168.1.5:42351"


def test_pairing_credentials_form_a_wifi_adb_payload():
    name, password, payload = make_pairing_credentials()

    assert name.startswith("adb-utils-")
    assert len(password) == 16
    assert payload == f"WIFI:T:ADB;S:{name};P:{password};;"


def test_wireless_qr_pixmap_is_generated(qtbot):
    _name, _password, payload = make_pairing_credentials()

    pixmap = make_qr_pixmap(payload, 240)

    assert not pixmap.isNull()
    assert 180 <= pixmap.width() <= 240
    assert pixmap.width() == pixmap.height()


class FakeProcess(QObject):
    finished = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.is_running = True
        self.cancelled = False

    def finish(self, ok: bool, stdout: str = "", stderr: str = "") -> None:
        self.is_running = False
        self.finished.emit(
            SimpleNamespace(
                ok=ok,
                stdout=stdout,
                stderr=stderr,
                cancelled=False,
            )
        )

    def cancel(self) -> None:
        self.cancelled = True
        self.is_running = False


class FakeAdb:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple, FakeProcess]] = []

    def run(self, *args, **kwargs):
        process = FakeProcess()
        self.calls.append((args, process))
        return process


def test_wireless_qr_pairs_then_connects(qtbot):
    adb = FakeAdb()
    dialog = WirelessQrDialog(adb)
    qtbot.addWidget(dialog)
    paired: list[str] = []
    dialog.paired.connect(paired.append)

    qtbot.waitUntil(lambda: len(adb.calls) == 1, timeout=2000)
    assert adb.calls[0][0][1:3] == ("mdns", "services")
    adb.calls[0][1].finish(
        True,
        "List of discovered mdns services\n"
        "adb-ABC\t_adb-tls-pairing._tcp\t192.168.1.5:37123\n",
    )

    qtbot.waitUntil(lambda: len(adb.calls) == 2, timeout=2000)
    assert adb.calls[1][0][1] == "pair"
    assert adb.calls[1][0][2] == "192.168.1.5:37123"
    adb.calls[1][1].finish(True, "Successfully paired to 192.168.1.5:37123")

    qtbot.waitUntil(lambda: len(adb.calls) >= 3, timeout=3000)
    mdns_index = len(adb.calls) - 1
    adb.calls[mdns_index][1].finish(
        True,
        "List of discovered mdns services\n"
        "adb-ABC\t_adb-tls-connect._tcp\t192.168.1.5:42351\n",
    )

    qtbot.waitUntil(
        lambda: any(call[0][1] == "connect" for call in adb.calls),
        timeout=2000,
    )
    connect_call = next(
        call for call in adb.calls if call[0][1] == "connect"
    )
    assert connect_call[0][2] == "192.168.1.5:42351"
    connect_call[1].finish(True, "connected to 192.168.1.5:42351")

    assert paired == ["192.168.1.5:42351"]


def test_any_device_can_be_hidden_and_returns_after_refresh(qtbot, tmp_path):
    page = DevicePage(make_context(tmp_path))
    qtbot.addWidget(page)
    page.context.set_devices(
        [
            DeviceInfo("AAA", "device", model="Phone A"),
            DeviceInfo("BBB", "device", model="Phone B"),
        ]
    )
    page.table.selectRow(0)

    page._delete_selected_device()

    assert page.table.rowCount() == 1
    assert page.context.is_device_hidden("AAA")
    page.context.clear_hidden_devices()
    assert page.table.rowCount() == 2


def test_manual_failed_device_can_be_selected_and_deleted(qtbot, tmp_path):
    page = DevicePage(make_context(tmp_path))
    qtbot.addWidget(page)

    page._add_manual("192.168.1.5:5555", "连接失败")
    assert page.manual_list.count() == 1
    assert page.remove_manual_button.isEnabled() is True

    page.manual_list.setCurrentRow(0)
    assert page.manual_list.currentItem().data(
        Qt.ItemDataRole.UserRole
    ) == "192.168.1.5:5555"
    page.remove_manual_button.click()

    assert page.manual_list.count() == 0
    assert page.remove_manual_button.isEnabled() is False
