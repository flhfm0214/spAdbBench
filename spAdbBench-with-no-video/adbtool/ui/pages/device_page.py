from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...infrastructure.parsers import DeviceInfo, parse_props
from ...services.danger import get_danger
from ...services.fastboot import FastbootCommandSession
from ...ui.page import BasePage
from ..widgets.danger_dialog import confirm_danger
from ..widgets.wireless_qr import WirelessQrDialog


STATE_TEXT = {
    "device": "已连接",
    "offline": "离线",
    "unauthorized": "未授权",
    "no permissions": "无权限",
    "recovery": "Recovery",
    "sideload": "Sideload",
    "bootloader": "Bootloader",
    "fastboot": "Fastboot",
}


class DevicePage(BasePage):
    def __init__(self, context) -> None:
        super().__init__(context)
        self._props_process = None
        self._props_serial = ""
        self.fastboot_session = FastbootCommandSession(context.adb, self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(10)

        header = QHBoxLayout()
        heading = QLabel("设备与连接")
        heading.setObjectName("SectionTitle")
        self.message_label = QLabel("选择设备后可执行连接、无线调试和重启操作。")
        self.message_label.setObjectName("Muted")
        header.addWidget(heading)
        header.addSpacing(12)
        header.addWidget(self.message_label, 1)
        self.refresh_button = QPushButton("刷新设备")
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["序列号", "状态", "型号", "传输 ID"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)

        table_actions = QHBoxLayout()
        self.use_button = QPushButton("使用此设备")
        self.use_button.setEnabled(False)
        table_actions.addWidget(self.use_button)
        table_actions.addStretch(1)
        layout.addLayout(table_actions)

        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(24)
        content_row.addWidget(self._build_wireless_group(), 1)
        content_row.addWidget(self._build_reboot_group(), 1)
        self.adb_panel = QWidget()
        self.adb_panel.setLayout(content_row)
        layout.addWidget(self.adb_panel)

        self.fastboot_group = self._build_fastboot_group()
        self.fastboot_group.hide()
        layout.addWidget(self.fastboot_group)

        self.info_group = self._build_info_group()
        layout.addWidget(self.info_group)

        self.refresh_button.clicked.connect(self._request_refresh)
        self.table.itemSelectionChanged.connect(self._update_selection_buttons)
        self.table.cellClicked.connect(self._on_cell_clicked)
        self.table.itemDoubleClicked.connect(lambda _item: self._use_selected_device())
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_device_menu)
        self.use_button.clicked.connect(self._use_selected_device)
        self.disconnect_button.clicked.connect(self._disconnect)
        self.qr_button.clicked.connect(self._open_qr_pairing)
        self.remove_manual_button.clicked.connect(self._delete_selected_or_manual)
        self.manual_list.itemSelectionChanged.connect(self._update_manual_buttons)
        self.manual_list.itemDoubleClicked.connect(self._use_manual_address)
        self.manual_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.manual_list.customContextMenuRequested.connect(
            self._show_manual_menu
        )
        self.context.devices_changed.connect(self._fill_table)
        self.context.fastboot_devices_changed.connect(self._fill_table)
        self.context.device_visibility_changed.connect(self._refresh_table)
        self.fastboot_session.error.connect(
            lambda message: self.context.status.error(f"Fastboot：{message}")
        )
        self.fastboot_session.finished.connect(self._on_fastboot_finished)
        self.fastboot_session.state.connect(self._on_fastboot_state)

    def _build_wireless_group(self) -> QGroupBox:
        group = QGroupBox("无线调试")
        layout = QGridLayout(group)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(6)

        self.address_edit = QLineEdit()
        self.address_edit.setPlaceholderText("IP:端口，例如 192.168.1.10:5555")
        self.pair_code = QLineEdit()
        self.pair_code.setPlaceholderText("配对码（仅配对时需要）")

        layout.addWidget(QLabel("地址"), 0, 0)
        layout.addWidget(self.address_edit, 0, 1, 1, 2)
        layout.addWidget(QLabel("配对码"), 1, 0)
        layout.addWidget(self.pair_code, 1, 1, 1, 2)

        self.pair_button = QPushButton("配对码配对")
        self.connect_button = QPushButton("连接")
        self.qr_button = QPushButton("二维码配对")
        self.qr_button.setObjectName("Primary")
        self.tcpip_button = QPushButton("切换 TCP/IP 5555")
        self.tcpip_button.setEnabled(False)
        layout.addWidget(self.pair_button, 2, 1)
        layout.addWidget(self.connect_button, 2, 2)
        layout.addWidget(self.qr_button, 3, 1)
        layout.addWidget(self.tcpip_button, 3, 2)

        self.manual_list = QListWidget()
        self.manual_list.setMaximumHeight(82)
        self.manual_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.manual_list.setToolTip("手动输入但未连接成功的记录会保留，右键可删除")
        self.disconnect_button = QPushButton("断开设备")
        self.disconnect_button.setEnabled(False)
        self.disconnect_button.setToolTip(
            "断开当前设备；USB 设备在刷新后会自动重新连接"
        )
        self.remove_manual_button = QPushButton("删除选中")
        self.remove_manual_button.setEnabled(False)
        self.remove_manual_button.setToolTip(
            "删除上方列表中单击选中的设备；未选中设备时删除手动记录"
        )
        device_actions = QHBoxLayout()
        device_actions.setContentsMargins(0, 0, 0, 0)
        device_actions.addWidget(self.disconnect_button)
        device_actions.addWidget(self.remove_manual_button)
        layout.addWidget(QLabel("设备操作"), 4, 0)
        layout.addLayout(device_actions, 4, 1, 1, 2)
        layout.addWidget(self.manual_list, 5, 1, 1, 2)
        self.manual_hint = QLabel("未连接的记录会保留；右键删除，双击回填地址。")
        self.manual_hint.setObjectName("Muted")
        self.manual_hint.setWordWrap(True)
        layout.addWidget(self.manual_hint, 6, 0, 1, 3)
        self.manual_list.hide()
        self.manual_hint.hide()

        self.pair_button.clicked.connect(self._pair)
        self.connect_button.clicked.connect(self._connect_network)
        self.tcpip_button.clicked.connect(self._tcpip)
        return group

    def _build_reboot_group(self) -> QGroupBox:
        group = QGroupBox("重启")
        layout = QGridLayout(group)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(6)

        self.reboot_buttons: dict[str, QPushButton] = {}
        actions = [
            ("重启设备", "system"),
            ("重启到 Bootloader", "bootloader"),
            ("重启到 Recovery", "recovery"),
            ("重启到 EDL", "edl"),
        ]
        for index, (label, mode) in enumerate(actions):
            button = QPushButton(label)
            button.setEnabled(False)
            button.clicked.connect(lambda _checked=False, m=mode: self._reboot(m))
            self.reboot_buttons[mode] = button
            layout.addWidget(button, index // 2, index % 2)
        return group

    def _build_fastboot_group(self) -> QGroupBox:
        group = QGroupBox("Fastboot 操作")
        layout = QGridLayout(group)
        layout.setContentsMargins(0, 8, 0, 4)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(10)

        actions = [
            ("重启到系统", "reboot", "reboot.system", False),
            ("重启到 Bootloader", "reboot bootloader", "reboot.bootloader", False),
            ("重启到 Recovery", "reboot recovery", "reboot.recovery", False),
            ("继续启动", "continue", "", False),
            ("重启到 EDL", "oem edl", "reboot.edl", True),
        ]
        self.fastboot_buttons: dict[str, QPushButton] = {}
        for index, (label, args, danger_key, is_danger) in enumerate(actions):
            button = QPushButton(label)
            button.setEnabled(False)
            # Every fastboot action shares one column width so the reboot
            # buttons keep identical sizes regardless of label length.
            button.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            if is_danger:
                button.setObjectName("Danger")
            button.clicked.connect(
                lambda _checked=False, a=args, k=danger_key, l=label: self._fastboot_reboot(
                    a, k, l
                )
            )
            self.fastboot_buttons[label] = button
            layout.addWidget(button, index // 3, index % 3)

        for column in range(3):
            layout.setColumnStretch(column, 1)
        return group

    def _fastboot_reboot(self, args: str, danger_key: str, label: str) -> None:
        device = self.context.current_device
        if device is None or device.state != "fastboot":
            self.context.status.error("当前没有可用的 fastboot 设备")
            return
        command = f"fastboot -s {device.serial} {args}"
        if danger_key and not confirm_danger(
            self, get_danger(danger_key, command=command)
        ):
            return
        self.context.status.info(f"正在执行：{label}")
        self.fastboot_session.start(device.serial, args)

    def _on_fastboot_state(self, state: str) -> None:
        if state.startswith("执行失败"):
            self.context.status.error(f"Fastboot：{state}")

    def _on_fastboot_finished(self, process) -> None:
        try:
            code = process.exitCode()
        except RuntimeError:
            return
        if code == 0:
            self.context.status.success("Fastboot 命令已完成")
        QTimer.singleShot(2500, self.context.device_service.refresh)

    def _build_info_group(self) -> QGroupBox:
        group = QGroupBox("设备信息")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(2)

        self._info_fields = (
            ("serial", "序列号"),
            ("model", "型号"),
            ("android", "Android 版本"),
            ("sdk", "SDK"),
            ("abi", "ABI"),
            ("build", "构建指纹"),
        )
        self._info_values = {key: "—" for key, _label in self._info_fields}
        self.info_text = QLabel()
        self.info_text.setObjectName("Value")
        self.info_text.setTextFormat(Qt.TextFormat.PlainText)
        self.info_text.setWordWrap(True)
        self.info_text.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.info_text.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.info_text.setCursor(Qt.CursorShape.IBeamCursor)
        layout.addWidget(self.info_text)
        self._render_info()
        return group

    def _render_info(self) -> None:
        values = self._info_values
        # One block keeps the whole device configuration selectable at once.
        self.info_text.setText(
            "\n".join(
                (
                    f"序列号：{values['serial']}    型号：{values['model']}",
                    f"Android 版本：{values['android']}    SDK：{values['sdk']}",
                    f"ABI：{values['abi']}",
                    f"构建指纹：{values['build']}",
                )
            )
        )

    def _set_info_values(self, **changes: str) -> None:
        self._info_values.update(changes)
        self._render_info()

    def _request_refresh(self) -> None:
        self.context.request_show_hidden_on_refresh()
        self.context.status.info("正在刷新设备列表…")
        self.context.device_service.refresh()

    def _refresh_table(self) -> None:
        self._fill_table(self.context.devices)

    def _fill_table(self, devices: list[DeviceInfo]) -> None:
        normalized: list[DeviceInfo] = []
        for item in devices:
            if hasattr(item, "state"):
                normalized.append(item)
            else:
                normalized.append(
                    DeviceInfo(
                        serial=item.serial,
                        state="fastboot",
                        model=item.serial,
                    )
                )
        devices = [
            device
            for device in normalized
            if not self.context.is_device_hidden(device.serial)
            and not self.context.is_device_disconnected(device.serial)
        ]
        for adb_device in self.context.devices:
            if self.context.is_device_hidden(adb_device.serial):
                continue
            if self.context.is_device_disconnected(adb_device.serial):
                continue
            if not any(device.serial == adb_device.serial for device in devices):
                devices.append(adb_device)
        for fastboot in self.context.fastboot_devices:
            if self.context.is_device_hidden(fastboot.serial):
                continue
            if self.context.is_device_disconnected(fastboot.serial):
                continue
            if not any(device.serial == fastboot.serial for device in devices):
                devices.append(
                    DeviceInfo(
                        serial=fastboot.serial,
                        state="fastboot",
                        model=fastboot.serial,
                    )
                )
        selected_serial = ""
        row = self.table.currentRow()
        if row >= 0:
            item = self.table.item(row, 0)
            if item is not None:
                selected_serial = item.text()

        self.table.setRowCount(0)
        for device in devices:
            row = self.table.rowCount()
            self.table.insertRow(row)
            serial_item = QTableWidgetItem(device.serial)
            serial_item.setData(Qt.ItemDataRole.UserRole, device)
            self.table.setItem(row, 0, serial_item)
            self.table.setItem(row, 1, QTableWidgetItem(STATE_TEXT.get(device.state, device.state)))
            self.table.setItem(row, 2, QTableWidgetItem(device.display_name))
            self.table.setItem(row, 3, QTableWidgetItem(device.transport_id or "—"))
            if device.serial == selected_serial:
                self.table.selectRow(row)

        self._update_selection_buttons()

    def _selected_device(self) -> DeviceInfo | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_cell_clicked(self, row: int, _column: int) -> None:
        # Make a single click in the table select that device for the
        # 「删除选中」 button, even when the click lands outside the current row.
        self.table.selectRow(row)
        self._update_selection_buttons()

    def _update_selection_buttons(self) -> None:
        device = self._selected_device()
        self.use_button.setEnabled(device is not None)
        self.remove_manual_button.setEnabled(
            device is not None or self.manual_list.count() > 0
        )
        self.disconnect_button.setEnabled(
            device is not None and device.connected
        )
        if device is not None:
            self.context.status.info(f"已选中 {device.serial}")
            self.context.select_device(device)

    def _delete_selected_or_manual(self) -> None:
        device = self._selected_device()
        if device is not None:
            self._delete_selected_device()
            return
        self._remove_manual()

    def _use_selected_device(self) -> None:
        device = self._selected_device()
        if device is not None:
            self.context.select_device(device)

    def _delete_selected_device(self) -> None:
        device = self._selected_device()
        if device is None:
            return
        self.context.hide_device(device.serial)
        self.context.status.info(
            f"已从列表删除 {device.serial}；离线设备刷新后不会再显示"
        )
        self._refresh_table()

    def _show_device_menu(self, pos) -> None:
        item = self.table.itemAt(pos)
        if item is None:
            return
        self.table.selectRow(item.row())
        device = self._selected_device()
        menu = QMenu(self)
        disconnect_action = menu.addAction("断开设备")
        disconnect_action.setEnabled(device is not None and device.connected)
        disconnect_action.triggered.connect(self._disconnect)
        menu.addSeparator()
        delete_action = menu.addAction("删除设备")
        delete_action.triggered.connect(self._delete_selected_device)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def on_device_changed(self, device: DeviceInfo | None) -> None:
        connected = device is not None and device.connected
        is_fastboot = device is not None and device.state == "fastboot"
        self.adb_panel.setEnabled(not is_fastboot)
        self.info_group.setEnabled(not is_fastboot)
        self.fastboot_group.setVisible(is_fastboot)
        self.disconnect_button.setEnabled(connected)
        if is_fastboot:
            self.disconnect_button.setEnabled(False)
        for button in self.fastboot_buttons.values():
            button.setEnabled(is_fastboot)
        self.tcpip_button.setEnabled(connected and not is_fastboot)
        for button in self.reboot_buttons.values():
            button.setEnabled(connected and not is_fastboot)

        if device is None:
            self._set_info_values(
                serial="—",
                model="—",
                android="—",
                sdk="—",
                abi="—",
                build="—",
            )
            if not self.context.config.auto_refresh_devices:
                self.message_label.setText(
                    "自动检测已关闭；点击「刷新设备」检测 ADB / Fastboot 设备。"
                )
            else:
                self.message_label.setText("未选择设备。")
            return

        self._set_info_values(
            serial=device.serial,
            model="—",
            android="—",
            sdk="—",
            abi="—",
            build="—",
        )
        if is_fastboot:
            self.message_label.setText(f"Fastboot 模式：{device.serial}。")
            return
        self.message_label.setText(f"当前设备：{device.display_name}（{device.serial}）")
        if connected and device.serial != self._props_serial:
            self._load_props(device.serial)

    def _load_props(self, serial: str) -> None:
        self._props_serial = serial
        if self._props_process is not None and self._props_process.is_running:
            self._props_process.cancel()
        process = self.context.adb.shell(serial, "getprop", timeout_ms=10000)
        self._props_process = process
        process.finished.connect(lambda result, s=serial: self._apply_props(s, result))

    def _apply_props(self, serial: str, result) -> None:
        if self.context.current_device is None or self.context.current_device.serial != serial:
            return
        if not result.ok:
            self.context.status.error(result.stderr.strip() or "读取设备属性失败")
            return
        props = parse_props(result.stdout)
        self._set_info_values(
            model=props.get("ro.product.model", "—"),
            android=props.get("ro.build.version.release", "—"),
            sdk=props.get("ro.build.version.sdk", "—"),
            abi=props.get("ro.product.cpu.abi", "—"),
            build=props.get("ro.build.fingerprint", "—"),
        )

    def _pair(self) -> None:
        address = self.address_edit.text().strip()
        code = self.pair_code.text().strip()
        if not address or not code:
            self.context.status.error("请输入配对地址和配对码")
            return
        self._add_manual(address, "配对中…")
        process = self.context.adb.run(None, "pair", address, code, timeout_ms=60000)
        self._track_manual(process, address, "配对")

    def _connect_network(self) -> None:
        address = self.address_edit.text().strip()
        if not address:
            self.context.status.error("请输入连接地址")
            return
        self._add_manual(address, "连接中…")
        process = self.context.adb.run(None, "connect", address, timeout_ms=30000)
        self._track_manual(process, address, "连接", refresh=True)

    def _manual_item(self, address: str) -> QListWidgetItem | None:
        for index in range(self.manual_list.count()):
            item = self.manual_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == address:
                return item
        return None

    def _add_manual(self, address: str, status: str, detail: str = "") -> None:
        address = (address or "").strip()
        if not address:
            return
        item = self._manual_item(address)
        if item is None:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, address)
            self.manual_list.addItem(item)
        item.setText(f"{address}  ·  {status}")
        item.setToolTip(detail or status)
        self.manual_list.setCurrentItem(item)
        self._update_manual_buttons()

    def _update_manual_buttons(self) -> None:
        has_records = self.manual_list.count() > 0
        self.remove_manual_button.setEnabled(
            self._selected_device() is not None or has_records
        )
        self.manual_list.setVisible(has_records)
        self.manual_hint.setVisible(has_records)

    def _remove_manual(self) -> None:
        row = self.manual_list.currentRow()
        if row < 0:
            row = self.manual_list.count() - 1
        if row < 0:
            return
        item = self.manual_list.takeItem(row)
        if item is not None:
            self.context.status.info(
                f"已删除手动设备记录：{item.data(Qt.ItemDataRole.UserRole)}"
            )
        self._update_manual_buttons()

    def _use_manual_address(self, item: QListWidgetItem) -> None:
        address = item.data(Qt.ItemDataRole.UserRole)
        if address:
            self.address_edit.setText(str(address))
            self.address_edit.setFocus()

    def _show_manual_menu(self, pos) -> None:
        item = self.manual_list.itemAt(pos)
        if item is None:
            return
        self.manual_list.setCurrentItem(item)
        menu = QMenu(self)
        delete_action = menu.addAction("删除记录")
        delete_action.triggered.connect(self._remove_manual)
        menu.exec(self.manual_list.viewport().mapToGlobal(pos))

    def _track_manual(
        self,
        process,
        address: str,
        action: str,
        refresh: bool = False,
    ) -> None:
        def _done(result) -> None:
            output = (result.stdout or result.stderr or "").strip()
            if result.ok:
                status = "已配对" if action == "配对" else "已连接"
                if action == "连接":
                    self.context.reconnect_device(address)
                self._add_manual(address, status, output)
                self.context.status.success(f"{action}成功：{address}")
                QTimer.singleShot(
                    1000 if refresh else 800,
                    self.context.device_service.refresh,
                )
            else:
                self._add_manual(address, f"{action}失败", output)
                self.context.status.error(
                    f"{action}失败：{output or '未知错误'}"
                )

        process.finished.connect(_done)

    def _open_qr_pairing(self) -> None:
        dialog = WirelessQrDialog(self.context.adb, self)
        dialog.paired.connect(self._on_qr_paired)
        dialog.exec()

    def _on_qr_paired(self, address: str) -> None:
        self.context.reconnect_device(address)
        self.address_edit.setText(address)
        self._add_manual(address, "二维码已连接")
        self.context.status.success(f"二维码配对已连接：{address}")
        QTimer.singleShot(600, self.context.device_service.refresh)

    def _tcpip(self) -> None:
        device = self.context.current_device
        if device is None:
            self.context.status.error("请先选择设备")
            return
        command = f"adb -s {device.serial} tcpip 5555"
        if not confirm_danger(self, get_danger("device.tcpip", command=command)):
            return
        process = self.context.adb.run(device.serial, "tcpip", "5555", timeout_ms=20000)
        self._report(process, "已切换为 TCP/IP 5555", refresh=True)

    def _reboot(self, mode: str) -> None:
        device = self.context.current_device
        if device is None:
            self.context.status.error("请先选择设备")
            return
        key = f"reboot.{mode}"
        command = f"adb -s {device.serial} reboot"
        if mode != "system":
            command += f" {mode}"
        if not confirm_danger(self, get_danger(key, command=command)):
            return
        args = ("reboot",) if mode == "system" else ("reboot", mode)
        process = self.context.adb.run(device.serial, *args, timeout_ms=15000)
        self._report(process, f"已发送重启命令（{mode}）", refresh=True, refresh_delay_ms=2500)

    def _disconnect(self) -> None:
        device = self._selected_device() or self.context.current_device
        if device is None:
            self.context.status.error("请先选择设备")
            return
        serial = device.serial
        if self.context.is_usb_serial(serial):
            # USB ADB cannot be closed with `adb disconnect`; detach it in the
            # app instead. A manual refresh attaches USB devices again.
            self.context.disconnect_device(serial)
            self.context.status.success(
                f"已断开设备 {serial}；刷新设备后 USB 连接会自动恢复"
            )
            self._refresh_table()
            return
        command = f"adb disconnect {serial}"
        if not confirm_danger(self, get_danger("device.disconnect", command=command)):
            return

        def _done(result) -> None:
            output = (result.stdout or result.stderr or "").strip()
            if result.ok:
                self.context.disconnect_device(serial)
                self.context.status.success(f"已断开设备：{serial}")
            else:
                self.context.status.error(f"断开设备失败：{output or '未知错误'}")
            QTimer.singleShot(300, self.context.device_service.refresh)

        process = self.context.adb.run(None, "disconnect", serial, timeout_ms=15000)
        process.finished.connect(_done)

    def _report(
        self,
        process,
        success_text: str,
        refresh: bool = False,
        refresh_delay_ms: int = 0,
    ) -> None:
        def _done(result) -> None:
            output = (result.stdout or result.stderr).strip()
            if result.ok:
                self.context.status.success(f"{success_text}：{output or '完成'}")
            else:
                self.context.status.error(f"{success_text}失败：{output or '未知错误'}")
            if refresh:
                QTimer.singleShot(refresh_delay_ms, self.context.device_service.refresh)

        process.finished.connect(_done)

    def on_activated(self) -> None:
        self._update_selection_buttons()
