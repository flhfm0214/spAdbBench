from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...infrastructure.parsers import DeviceInfo
from ...services.fastboot import FastbootCommandSession
from ...services.packages import PackageService, parse_package_listing
from ...services.terminal import (
    AdbCommandSession,
    CommandSpec,
    CompletionCatalog,
    TerminalSession,
    command_specs,
)
from ..page import BasePage
from ..widgets.terminal_guide import TerminalGuideDialog
from ..widgets.terminal_view import TerminalView


MAX_LISTED_CANDIDATES = 50
EXIT_SEPARATOR = "----------{time}，{name}已退出-----------"


class TerminalPage(BasePage):
    def __init__(self, context) -> None:
        super().__init__(context)
        self.adb_session = AdbCommandSession(context.adb)
        self.session = TerminalSession(context.adb)
        self.fastboot_session = FastbootCommandSession(context.adb, self)
        self.package_service = PackageService(context.adb)
        self.catalog = CompletionCatalog(context.config_store.root)
        self.command_specs = command_specs()
        self._specs_by_name: dict[str, CommandSpec] = {}
        self._specs_by_layer: dict[tuple[str, str], CommandSpec] = {}
        for spec in self.command_specs:
            self._specs_by_name.setdefault(spec.name, spec)
            self._specs_by_layer.setdefault((spec.layer, spec.name), spec)
        self._serial = ""
        self._fastboot_serial = ""
        self._device_name = ""
        self._fastboot_name = ""
        self._auto_fastboot_serial = ""
        self._mode = "adb"
        self._package_process = None
        self._history: list[str] = []
        self._history_index = 0
        self._draft = ""
        self._auto_connect = True
        self._editable = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        header = QHBoxLayout()
        heading = QLabel("终端")
        heading.setObjectName("SectionTitle")
        self.message_label = QLabel("默认 ADB 模式；可切换设备 shell。")
        self.message_label.setObjectName("Muted")
        self.state_label = QLabel("未连接设备")
        self.state_label.setObjectName("Muted")
        header.addWidget(heading)
        header.addSpacing(12)
        header.addWidget(self.message_label, 1)
        header.addWidget(self.state_label)
        layout.addLayout(header)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("ADB 命令", "adb")
        self.mode_combo.addItem("Shell 命令", "shell")
        self.mode_combo.addItem("Fastboot 命令", "fastboot")
        self.mode_combo.setMinimumWidth(126)
        self._update_fastboot_option()
        self.reconnect_button = QPushButton("重连")
        self.reconnect_button.setObjectName("Primary")
        self.stop_button = QPushButton("停止")
        self.clear_button = QPushButton("清屏")
        self.copy_button = QPushButton("复制全部")
        toolbar.addWidget(self.mode_combo)
        toolbar.addWidget(self.reconnect_button)
        toolbar.addWidget(self.stop_button)
        toolbar.addWidget(self.clear_button)
        toolbar.addWidget(self.copy_button)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self.device_hint = QLabel("")
        self.device_hint.setObjectName("WarningText")
        self.device_hint.setWordWrap(True)
        self.device_hint.hide()
        layout.addWidget(self.device_hint)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_terminal_box())
        splitter.addWidget(self._build_command_panel())
        splitter.setSizes([430, 220])
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        self.terminal.submitted.connect(self._on_submitted)
        self.terminal.tab_pressed.connect(self._handle_tab)
        self.terminal.history_previous.connect(self._history_up)
        self.terminal.history_next.connect(self._history_down)
        self.terminal.interrupt_requested.connect(self._interrupt)
        self.terminal.clear_requested.connect(self._clear_output)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.reconnect_button.clicked.connect(self._connect_session)
        self.stop_button.clicked.connect(self._disconnect_session)
        self.clear_button.clicked.connect(self._clear_output)
        self.copy_button.clicked.connect(self._copy_all)
        self.guide_shortcut = QShortcut(QKeySequence("F1"), self)
        self.guide_shortcut.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut
        )
        self.guide_shortcut.activated.connect(self._open_guide)
        self.command_search.textChanged.connect(self._filter_commands)
        self.command_table.cellDoubleClicked.connect(self._fill_command)
        self.command_table.itemSelectionChanged.connect(
            self._show_command_detail
        )
        self.adb_session.output.connect(self._append_output)
        self.adb_session.state.connect(self._on_adb_state)
        self.adb_session.error.connect(self._on_session_error)
        self.adb_session.finished.connect(self._on_adb_finished)
        self.session.output.connect(self._append_output)
        self.session.state.connect(self._on_shell_state)
        self.session.error.connect(self._on_session_error)
        self.context.fastboot_devices_changed.connect(self._on_fastboot_devices)
        self.fastboot_session.output.connect(self._append_output)
        self.fastboot_session.state.connect(self._on_fastboot_state)
        self.fastboot_session.error.connect(self._on_session_error)
        self.fastboot_session.finished.connect(self._on_fastboot_finished)

        self._render_command_table()
        self._apply_mode("adb", reset=True)
        self._update_controls()

    def _build_terminal_box(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.terminal_frame = QWidget()
        self.terminal_frame.setObjectName("TerminalFrame")
        frame_layout = QVBoxLayout(self.terminal_frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(0)

        self.terminal = TerminalView()
        self.terminal.setObjectName("TerminalOutput")
        self.terminal.setPlaceholderText("终端输出")
        self.input = self.terminal
        self.output = self.terminal
        frame_layout.addWidget(self.terminal, 1)

        layout.addWidget(self.terminal_frame, 1)
        return box

    def _build_command_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumHeight(110)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(6)

        header = QHBoxLayout()
        label = QLabel("命令速查（ADB + Shell + Fastboot）")
        label.setObjectName("Muted")
        self.command_search = QLineEdit()
        self.command_search.setPlaceholderText("搜索命令、语法或说明")
        self.command_search.setClearButtonEnabled(True)
        self.command_count = QLabel("")
        self.command_count.setObjectName("Muted")
        header.addWidget(label)
        header.addWidget(self.command_search, 1)
        header.addWidget(self.command_count)
        layout.addLayout(header)

        self.command_table = QTableWidget(0, 4)
        self.command_table.setHorizontalHeaderLabels(
            ["类型", "命令", "语法", "说明"]
        )
        self.command_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.command_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.command_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.command_table.setAlternatingRowColors(True)
        self.command_table.setWordWrap(False)
        self.command_table.setMinimumHeight(70)
        self.command_table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored
        )
        self.command_table.verticalHeader().setVisible(False)
        table_header = self.command_table.horizontalHeader()
        table_header.setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        table_header.setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        table_header.setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        table_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.command_table.setToolTip("双击命令切换对应模式并填入输入框")
        layout.addWidget(self.command_table, 1)
        self.command_detail = QLabel("选择命令查看完整语法。")
        self.command_detail.setObjectName("Muted")
        self.command_detail.setWordWrap(True)
        layout.addWidget(self.command_detail)
        return panel

    def _render_command_table(self) -> None:
        self.command_table.setUpdatesEnabled(False)
        try:
            self.command_table.setRowCount(len(self.command_specs))
            for row, spec in enumerate(self.command_specs):
                values = [spec.layer, spec.name, spec.syntax, spec.description]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setToolTip(value)
                    self.command_table.setItem(row, column, item)
        finally:
            self.command_table.setUpdatesEnabled(True)
        self._filter_commands()
        self._refresh_command_availability()

    def _filter_commands(self) -> None:
        query = self.command_search.text().strip().lower()
        visible = 0
        for row, spec in enumerate(self.command_specs):
            haystack = (
                f"{spec.layer} {spec.name} {spec.syntax} {spec.description}"
            ).lower()
            hidden = bool(query) and query not in haystack
            self.command_table.setRowHidden(row, hidden)
            if not hidden:
                visible += 1
        current = self.command_table.currentRow()
        if current >= 0 and self.command_table.isRowHidden(current):
            self.command_table.clearSelection()
            self.command_detail.setText("选择命令查看完整语法。")
        self.command_count.setText(f"{visible}/{len(self.command_specs)} 条")

    def _show_command_detail(self) -> None:
        row = self.command_table.currentRow()
        if not 0 <= row < len(self.command_specs):
            self.command_detail.setText("选择命令查看完整语法。")
            return
        spec = self.command_specs[row]
        self.command_detail.setText(f"{spec.syntax}    {spec.description}")

    def _fill_command(self, row: int, _column: int) -> None:
        if not 0 <= row < len(self.command_specs):
            return
        spec = self.command_specs[row]
        if spec.layer == "shell":
            target_mode = "shell"
        elif spec.layer == "Fastboot":
            if self._mode != "fastboot":
                self.context.status.info("切换到 Fastboot 模式后可用")
                return
            target_mode = "fastboot"
        else:
            target_mode = "adb"
        if self._mode != target_mode:
            index = self.mode_combo.findData(target_mode)
            if index >= 0:
                self.mode_combo.setCurrentIndex(index)
        self.terminal.set_input_text(f"{spec.name} ")
        self.terminal.set_cursor_end()
        self.terminal.setFocus()

    @property
    def mode(self) -> str:
        return self._mode

    def on_activated(self) -> None:
        self._on_fastboot_devices(self.context.fastboot_devices)
        if (
            self._mode == "shell"
            and self._serial
            and self._auto_connect
            and not self.session.running
        ):
            self._connect_session()
        elif self._mode == "adb" and self._serial:
            self.state_label.setText("ADB 就绪")
        self._update_device_hint()
        self._update_controls()

    def on_deactivated(self) -> None:
        return

    def on_device_changed(self, device: DeviceInfo | None) -> None:
        serial = device.serial if device and device.connected else ""
        changed = serial != self._serial
        if changed:
            if self._serial:
                self._append_exit(self._device_name or self._serial)
            if self._mode != "fastboot":
                self._stop_all()
            self._serial = serial
            self._device_name = device.display_name if device else ""
            self._auto_connect = True
            self.catalog.set_packages([])
            if self._mode != "fastboot":
                self._load_packages()
        if not serial:
            if self._mode == "fastboot":
                self.message_label.setText(
                    f"当前 fastboot 设备：{self._fastboot_serial or '未连接'}"
                )
            else:
                self.message_label.setText("未选择设备。")
                self.state_label.setText("未连接设备")
        else:
            if self._mode == "fastboot":
                self.message_label.setText(f"当前 fastboot 设备：{self._fastboot_serial}")
            else:
                self.message_label.setText(f"当前设备：{serial}")
                if self._mode == "shell":
                    if changed and self._auto_connect:
                        self._connect_session()
                else:
                    self.state_label.setText("ADB 就绪")
        self._update_device_hint()
        self._update_controls()

    def shutdown(self) -> None:
        self._cancel_package_load(wait=True)
        self.adb_session.stop()
        self.adb_session.wait(1500)
        self.session.stop()
        self.session.wait(1500)
        self.fastboot_session.stop()
        self.fastboot_session.wait(1500)

    def _apply_mode(self, mode: str, reset: bool = False) -> None:
        self._mode = mode
        prompt = {"adb": "adb> ", "shell": "shell> ", "fastboot": "fastboot> "}[mode]
        if reset or self.terminal.prompt != prompt:
            self.terminal.set_prompt(prompt, reset=False)
        self._auto_connect = True
        if mode == "fastboot":
            if self._fastboot_serial:
                self.state_label.setText("Fastboot 就绪")
            else:
                self.state_label.setText("等待 fastboot 设备")
        elif not self._serial:
            self.state_label.setText("未连接设备")
        elif mode == "adb":
            self.state_label.setText("ADB 就绪")
        else:
            self.state_label.setText("就绪")
        self._update_device_hint()
        self._update_controls()
        self._refresh_command_availability()

    def _refresh_command_availability(self) -> None:
        """Gray out Fastboot rows outside Fastboot mode."""
        fastboot_mode = self._mode == "fastboot"
        for row, spec in enumerate(self.command_specs):
            if spec.layer != "Fastboot":
                continue
            values = [spec.layer, spec.name, spec.syntax, spec.description]
            for column in range(4):
                item = self.command_table.item(row, column)
                if item is None:
                    continue
                if fastboot_mode:
                    item.setFlags(
                        item.flags()
                        | Qt.ItemFlag.ItemIsEnabled
                        | Qt.ItemFlag.ItemIsSelectable
                    )
                    item.setData(Qt.ItemDataRole.ForegroundRole, None)
                    item.setToolTip(values[column])
                else:
                    item.setFlags(
                        item.flags()
                        & ~Qt.ItemFlag.ItemIsEnabled
                        & ~Qt.ItemFlag.ItemIsSelectable
                    )
                    item.setForeground(QBrush(QColor("#8b949e")))
                    item.setToolTip("切换到 Fastboot 模式后可用")
        current = self.command_table.currentRow()
        if (
            not fastboot_mode
            and 0 <= current < len(self.command_specs)
            and self.command_specs[current].layer == "Fastboot"
        ):
            self.command_table.clearSelection()
            self.command_detail.setText("切换到 Fastboot 模式后可用。")

    def _on_mode_changed(self, _index: int) -> None:
        mode = self.mode_combo.currentData()
        if mode == self._mode:
            return
        self._stop_all()
        self._apply_mode(mode, reset=True)
        if mode == "fastboot":
            self._update_fastboot_option()
            self._update_device_hint()
            self.terminal.setFocus()
            if self._fastboot_serial:
                self.context.status.info(f"Fastboot：{self._fastboot_serial}")
            else:
                self.context.status.info("Fastboot 模式：等待设备连接")
        elif mode == "shell" and self._serial:
            self._connect_session()
        elif mode == "adb" and self._serial:
            self.state_label.setText("ADB 就绪")
            self.terminal.setFocus()

    def _stop_all(self) -> None:
        self.adb_session.stop()
        self.session.stop()
        self.fastboot_session.stop()

    def _connect_session(self) -> None:
        if self._mode == "fastboot":
            if self._fastboot_serial:
                self.state_label.setText("Fastboot 就绪")
                self.terminal.setFocus()
            self._update_controls()
            return
        if not self._serial:
            return
        if self._mode == "adb":
            self.state_label.setText("ADB 就绪")
            self.terminal.setFocus()
            self._update_controls()
            return
        self._auto_connect = True
        self.session.start(self._serial)
        self._update_controls()

    def _disconnect_session(self) -> None:
        self._auto_connect = False
        if self._mode == "fastboot":
            self.fastboot_session.stop()
            self.state_label.setText("Fastboot 就绪")
        elif self._mode == "adb":
            self.adb_session.stop()
            if self._serial:
                self.state_label.setText("ADB 就绪")
        else:
            self.session.stop()
        self._update_controls()

    def _on_adb_state(self, state: str) -> None:
        if state == "已完成" and self._serial:
            self.state_label.setText("ADB 就绪")
        else:
            self.state_label.setText(state)
        self._update_controls()

    def _on_adb_finished(self, _result) -> None:
        self.terminal.flush_output()
        if self._serial:
            self.state_label.setText("ADB 就绪")
        self._update_controls()

    def _on_shell_state(self, state: str) -> None:
        self.state_label.setText(state)
        if state == "已连接":
            self.terminal.setFocus()
        elif state in {"已停止", "已断开", "连接失败"}:
            self.terminal.flush_output()
        self._update_controls()

    def _on_fastboot_state(self, state: str) -> None:
        self.state_label.setText(state)
        if state == "已完成":
            self.terminal.flush_output()
            self.state_label.setText("Fastboot 就绪")
        self._update_controls()

    def _on_fastboot_finished(self, _process) -> None:
        self.terminal.flush_output()
        if self._fastboot_serial:
            self.state_label.setText("Fastboot 就绪")
        self._update_controls()

    def _on_fastboot_devices(self, devices) -> None:
        previous = self._fastboot_serial
        previous_name = self._fastboot_name
        available = list(devices)
        self._fastboot_serial = available[0].serial if available else ""
        self._fastboot_name = self._fastboot_serial
        self._update_fastboot_option()
        if previous and previous != self._fastboot_serial:
            self._append_exit(previous_name or previous)
        if not self._fastboot_serial:
            self._auto_fastboot_serial = ""
        if previous != self._fastboot_serial:
            if self._mode == "fastboot":
                self.fastboot_session.stop()
                if not self._fastboot_serial:
                    self.mode_combo.blockSignals(True)
                    self.mode_combo.setCurrentIndex(
                        max(0, self.mode_combo.findData("adb"))
                    )
                    self.mode_combo.blockSignals(False)
                    self._apply_mode("adb", reset=True)
                else:
                    self.state_label.setText("Fastboot 就绪")
            elif self._serial:
                self.message_label.setText(f"当前设备：{self._serial}")
        elif self._mode == "fastboot" and self._fastboot_serial:
            self.message_label.setText(f"当前 fastboot 设备：{self._fastboot_serial}")
            self.state_label.setText("Fastboot 就绪")

        if (
            self._fastboot_serial
            and self._auto_fastboot_serial != self._fastboot_serial
        ):
            self._auto_fastboot_serial = self._fastboot_serial
            index = self.mode_combo.findData("fastboot")
            if index >= 0 and self._mode != "fastboot":
                self.mode_combo.setCurrentIndex(index)
                self.context.status.info(
                    f"检测到 fastboot 设备，已切换终端：{self._fastboot_serial}"
                )

        self._update_device_hint()
        self._update_controls()

    def _update_fastboot_option(self) -> None:
        index = self.mode_combo.findData("fastboot")
        if index < 0:
            return
        model = self.mode_combo.model()
        item = model.item(index) if hasattr(model, "item") else None
        active = bool(self._fastboot_serial)
        if item is not None:
            item.setEnabled(True)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEnabled)
            item.setData(None, Qt.ItemDataRole.ForegroundRole)
            item.setToolTip(
                f"Fastboot 设备：{self._fastboot_serial}"
                if active
                else "Fastboot 模式：未连接时显示等待提示"
            )
        self.mode_combo.setItemData(
            index,
            "Fastboot 模式" if not active else "Fastboot 设备已连接",
            Qt.ItemDataRole.ToolTipRole,
        )

    def _active_serial(self) -> str:
        if self._mode == "fastboot":
            return self._fastboot_serial
        return self._serial

    def _update_device_hint(self) -> None:
        if self._active_serial():
            self.device_hint.hide()
            return
        if self._mode == "fastboot":
            text = (
                "等待设备连接：请让设备进入 bootloader / fastboot 模式，"
                "并通过 USB 连接。"
            )
        else:
            text = (
                "等待设备连接：请通过 USB 连接设备，并在手机上允许 USB 调试。"
            )
        self.device_hint.setText(text)
        self.device_hint.show()

    def _on_session_error(self, message: str) -> None:
        self.terminal.append_output(f"[错误] {message}\n")
        self.context.status.error(f"终端：{message}")
        self._update_controls()

    def _on_submitted(self, command: str) -> None:
        if self._mode == "fastboot":
            if not self._fastboot_serial:
                self._update_device_hint()
                self.terminal.append_output("[错误] 等待 fastboot 设备连接\n")
                return
            self._remember(command)
            if self.fastboot_session.running:
                self.terminal.append_output("[提示] 上一条 fastboot 命令仍在执行\n")
                return
            self.fastboot_session.start(self._fastboot_serial, command)
            return
        if not self._serial:
            self._update_device_hint()
            self.terminal.append_output("[错误] 请先连接设备\n")
            return
        self._remember(command)
        if self._mode == "adb":
            if self.adb_session.running:
                self.terminal.append_output("[提示] 上一条 ADB 命令仍在执行\n")
                return
            self.adb_session.start(self._serial, command)
            return
        if not self.session.running:
            self.terminal.append_output("[错误] Shell 未连接\n")
            return
        self.session.send(command)

    def _append_output(self, text: str) -> None:
        self.terminal.append_output(text)
        self._update_controls()

    def _append_exit(self, name: str) -> None:
        if not name:
            return
        stamp = datetime.now().strftime("%H:%M:%S")
        self.terminal.append_output(
            EXIT_SEPARATOR.format(time=stamp, name=name) + "\n"
        )
        self.terminal.flush_output()

    def _remember(self, text: str) -> None:
        if not self._history or self._history[-1] != text:
            self._history.append(text)
            del self._history[:-200]
        self._history_index = len(self._history)
        self._draft = ""

    def _history_up(self) -> None:
        if not self._history:
            return
        if self._history_index == len(self._history):
            self._draft = self.terminal.input_text()
        self._history_index = max(0, self._history_index - 1)
        self.terminal.set_input_text(self._history[self._history_index])
        self.terminal.set_cursor_end()

    def _history_down(self) -> None:
        if not self._history:
            return
        if self._history_index < len(self._history) - 1:
            self._history_index += 1
            self.terminal.set_input_text(self._history[self._history_index])
        else:
            self._history_index = len(self._history)
            self.terminal.set_input_text(self._draft)
        self.terminal.set_cursor_end()

    def _interrupt(self) -> None:
        if self._mode == "fastboot":
            self.fastboot_session.interrupt()
        elif self._mode == "adb":
            if self.adb_session.running:
                self.adb_session.interrupt()
        elif self.session.running:
            self.session.interrupt()
        self.terminal.append_output("^C\n")

    def _clear_output(self) -> None:
        self.terminal.clear_terminal()
        self._update_controls()

    def _copy_all(self) -> None:
        text = self.terminal.toPlainText()
        if not text:
            self.context.status.info("终端没有可复制的内容")
            return
        self.terminal.copy_all()
        self.context.status.success("终端输出已复制")

    def _open_guide(self) -> None:
        TerminalGuideDialog(self).exec()

    def _load_packages(self) -> None:
        self._cancel_package_load()
        if not self._serial:
            return
        serial = self._serial
        process = self.package_service.list_packages(serial)
        self._package_process = process
        process.finished.connect(
            lambda result, s=serial, p=process: self._on_packages_loaded(
                s, p, result
            )
        )

    def _cancel_package_load(self, wait: bool = False) -> None:
        process = self._package_process
        self._package_process = None
        if process is not None and process.is_running:
            process.cancel()
        if wait and process is not None:
            process.wait(1500)

    def _on_packages_loaded(self, serial: str, process, result) -> None:
        if process is not self._package_process or serial != self._serial:
            return
        self._package_process = None
        if not result.ok:
            self.context.status.info("终端补全包名加载失败，仍可使用命令补全")
            return
        packages = [
            info.package for info in parse_package_listing(result.stdout)
        ]
        self.catalog.set_packages(packages)
        if packages:
            self.context.status.info(f"终端补全已加载 {len(packages)} 个包名")

    def _completion_context(self) -> tuple[
        int, str, list[str], dict[str, CommandSpec]
    ]:
        text = self.terminal.input_text()
        stripped = text.lstrip()
        leading = len(text) - len(stripped)
        if self._mode == "fastboot":
            return self._complete_prefixed_command(
                text,
                leading,
                "fastboot",
                self.catalog.static_fastboot_commands(),
                "Fastboot",
            )
        if self._mode == "adb":
            return self._complete_prefixed_command(
                text,
                leading,
                "adb",
                self.catalog.static_adb_commands(),
                "ADB",
            )
        return self._complete_shell(text, leading)

    def _complete_prefixed_command(
        self,
        text: str,
        leading: int,
        keyword: str,
        commands: list[str],
        layer: str,
    ) -> tuple[int, str, list[str], dict[str, CommandSpec]]:
        stripped = text.lstrip()
        marker = f"{keyword} "
        if stripped.startswith(marker):
            body = stripped[len(marker):]
            start = leading + len(marker)
        else:
            body = stripped
            start = leading
        if not body:
            shown = commands[:20]
            return start, "", shown, self._top_specs(shown, layer)

        tokens = body.split()
        if len(tokens) == 1 and not body.endswith(" "):
            token = tokens[0]
            candidates = [
                command for command in commands if command.startswith(token)
            ]
            return (
                len(text) - len(token),
                token,
                candidates,
                self._top_specs(candidates, layer),
            )

        command = tokens[0]
        trailing = body.endswith(" ")
        if len(tokens) == 1:
            path: tuple[str, ...] = ()
            prefix = ""
            start = len(text)
        elif trailing:
            path = tuple(tokens[1:])
            prefix = ""
            start = len(text)
        else:
            path = tuple(tokens[1:-1])
            prefix = tokens[-1]
            start = len(text) - len(prefix)
        options = self.catalog.complete_command(command, path, prefix)
        return (
            start,
            prefix,
            [option.name for option in options],
            self._option_specs(options, layer),
        )

    def _complete_shell(
        self,
        text: str,
        leading: int,
    ) -> tuple[int, str, list[str], dict[str, CommandSpec]]:
        stripped = text.lstrip()
        pipe = self._last_pipe_index(stripped)
        if pipe >= 0:
            # Only the command after the last pipe is being edited. The
            # earlier pipeline stages keep their own arguments and are not
            # re-parsed as part of this command.
            segment = stripped[pipe + 1:]
            offset = leading + pipe + 1
        else:
            segment = stripped
            offset = leading
        return self._complete_shell_segment(
            text,
            segment,
            offset,
            after_pipe=pipe >= 0,
        )

    @staticmethod
    def _last_pipe_index(text: str) -> int:
        quote = ""
        escaped = False
        last = -1
        for index, char in enumerate(text):
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if quote:
                if char == quote:
                    quote = ""
                continue
            if char in ("'", '"'):
                quote = char
                continue
            if char == "|":
                last = index
        return last

    def _complete_shell_segment(
        self,
        text: str,
        segment: str,
        offset: int,
        *,
        after_pipe: bool = False,
    ) -> tuple[int, str, list[str], dict[str, CommandSpec]]:
        stripped = segment.lstrip()
        base = offset + len(segment) - len(stripped)
        commands = self.catalog.shell_commands()
        if not stripped:
            shown = (
                self.catalog.pipe_commands() if after_pipe else commands[:20]
            )
            return base, "", shown, self._top_specs(shown, "shell")

        tokens = stripped.split()
        if len(tokens) == 1 and not stripped.endswith(" "):
            token = tokens[0]
            candidates = [
                command for command in commands if command.startswith(token)
            ]
            return (
                len(text) - len(token),
                token,
                candidates,
                self._top_specs(candidates, "shell"),
            )

        command = tokens[0]
        trailing = stripped.endswith(" ")
        if len(tokens) == 1:
            path: tuple[str, ...] = ()
            prefix = ""
            start = len(text)
        elif trailing:
            path = tuple(tokens[1:])
            prefix = ""
            start = len(text)
        else:
            path = tuple(tokens[1:-1])
            prefix = tokens[-1]
            start = len(text) - len(prefix)
        options = self.catalog.complete_command(command, path, prefix)
        return (
            start,
            prefix,
            [option.name for option in options],
            self._option_specs(options, "shell"),
        )

    def _top_specs(
        self,
        candidates: list[str],
        layer: str,
    ) -> dict[str, CommandSpec]:
        return {
            candidate: self._specs_by_layer[(layer, candidate)]
            for candidate in candidates
            if (layer, candidate) in self._specs_by_layer
        }

    @staticmethod
    def _option_specs(
        options,
        layer: str,
    ) -> dict[str, CommandSpec]:
        specs: dict[str, CommandSpec] = {}
        for option in options:
            if not option.syntax:
                continue
            specs.setdefault(
                option.name,
                CommandSpec(
                    name=option.name,
                    syntax=option.syntax,
                    description=option.description or "命令选项",
                    layer=layer,
                ),
            )
        return specs

    def _handle_tab(self) -> None:
        start, prefix, candidates, specs = self._completion_context()
        if not candidates:
            self.terminal.setFocus()
            return
        if len(candidates) == 1:
            self._apply_completion(candidates[0], start)
            return
        common = _common_prefix(candidates)
        if len(common) > len(prefix):
            text = self.terminal.input_text()
            self.terminal.set_input_text(f"{text[:start]}{common}")
            self.terminal.set_cursor_end()
        self._print_candidates(candidates, specs)
        self.terminal.setFocus()

    def _apply_completion(self, value: str, start: int) -> None:
        text = self.terminal.input_text()
        self.terminal.set_input_text(f"{text[:start]}{value} ")
        self.terminal.set_cursor_end()
        self.terminal.setFocus()

    def _print_candidates(
        self,
        candidates: list[str],
        specs: dict[str, CommandSpec] | None = None,
    ) -> None:
        shown = candidates[:MAX_LISTED_CANDIDATES]
        specs = specs or {}
        lines = [f"候选（{len(candidates)}）："]
        for candidate in shown:
            spec = specs.get(candidate) or self._specs_by_name.get(candidate)
            if spec is None:
                lines.append(f"  {candidate}")
            else:
                lines.append(f"  {candidate:<16} {spec.syntax}")
        if len(candidates) > len(shown):
            lines.append(
                f"  … 还有 {len(candidates) - len(shown)} 个，请继续输入前缀"
            )
        self.terminal.append_output("\n" + "\n".join(lines) + "\n")
        self.terminal.setFocus()

    def _update_controls(self) -> None:
        connected = bool(self._active_serial())
        adb_running = self.adb_session.running
        shell_running = self.session.running
        fastboot_running = self.fastboot_session.running
        if self._mode == "adb":
            running = adb_running
        elif self._mode == "shell":
            running = shell_running
        else:
            running = fastboot_running
        shell_mode = self._mode == "shell"
        self.reconnect_button.setVisible(shell_mode)
        self.reconnect_button.setEnabled(connected and shell_mode)
        self.stop_button.setEnabled(running)
        has_output = self.terminal.toPlainText() != self.terminal.prompt
        self.clear_button.setEnabled(has_output)
        self.copy_button.setEnabled(has_output)
        editable = connected and (
            self._mode in {"adb", "fastboot"} or shell_running
        )
        if editable != self._editable:
            self._editable = editable
            self.terminal.set_editable(editable)
        self._update_device_hint()


def _common_prefix(values: list[str]) -> str:
    if not values:
        return ""
    prefix = values[0]
    for value in values[1:]:
        while not value.startswith(prefix):
            prefix = prefix[:-1]
            if not prefix:
                return ""
    return prefix
