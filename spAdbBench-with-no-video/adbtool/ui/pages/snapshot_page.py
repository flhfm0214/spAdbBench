from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ...infrastructure.parsers import DeviceInfo
from ...services.danger import get_danger
from ...services.snapshot import CompareRow, SnapshotDeviceMismatch
from ...services.snapshot_files import (
    DeviceSnapshot,
    SnapshotDocument,
    SnapshotFormatError,
    load_snapshot,
    save_snapshot,
)
from ..page import BasePage
from ..widgets.danger_dialog import DangerDialog
from ..widgets.result_dialog import show_results


def default_snapshot_name(serial: str, now: datetime | None = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    safe_serial = "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "_"
        for char in (serial or "device")
    )
    return f"adbtool-snapshot-{safe_serial}-{stamp}.json"


def _display_value(value: str | None) -> str:
    if value is None or value == "":
        return "未设置"
    return value


def _display_time(value: str) -> str:
    if not value:
        return "—"
    text = value.replace("T", " ")
    return text[:19] if len(text) >= 19 else text


class SnapshotPage(BasePage):
    def __init__(self, context) -> None:
        super().__init__(context)
        self._serial = ""
        self._document: SnapshotDocument | None = None
        self._snapshot: DeviceSnapshot | None = None
        self._rows: list[CompareRow] = []
        self._row_index: dict[str, int] = {}
        self._entries: list[tuple[Path, DeviceSnapshot]] = []
        self._capture_job = None
        self._compare_job = None
        self._rollback_job = None
        self._rollback_rows: list[CompareRow] = []
        self._rollback_results: list[tuple[str, bool, str]] = []
        self._pending_rollback_rows: list[CompareRow] = []
        self._closing = False

        self.last_confirmation_text = ""
        self.danger_dialog: DangerDialog | None = None
        self.last_saved_path: Path | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(10)

        header = QHBoxLayout()
        heading = QLabel("配置快照")
        heading.setObjectName("SectionTitle")
        self.device_label = QLabel("当前设备：未选择")
        self.device_label.setObjectName("Muted")
        self.device_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.export_button = QPushButton("导出当前配置")
        self.export_button.setObjectName("Primary")
        self.import_button = QPushButton("导入快照")
        self.refresh_button = QPushButton("刷新列表")
        header.addWidget(heading)
        header.addSpacing(12)
        header.addWidget(self.device_label, 1)
        header.addWidget(self.export_button)
        header.addWidget(self.import_button)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        progress_row = QHBoxLayout()
        self.message_label = QLabel("导出会逐项读取设备配置；导入后可对比并回滚。")
        self.message_label.setObjectName("Muted")
        self.message_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setMaximumWidth(360)
        self.progress_bar.hide()
        self.cancel_button = QPushButton("取消导出")
        self.cancel_button.hide()
        progress_row.addWidget(self.message_label, 1)
        progress_row.addWidget(self.progress_bar)
        progress_row.addWidget(self.cancel_button)
        layout.addLayout(progress_row)

        layout.addWidget(self._build_snapshot_group(), 2)
        layout.addWidget(self._build_compare_group(), 3)

        self.export_button.clicked.connect(self._start_capture)
        self.import_button.clicked.connect(self._import_snapshot)
        self.refresh_button.clicked.connect(self._refresh_snapshots)
        self.cancel_button.clicked.connect(self._cancel_capture)
        self.compare_button.clicked.connect(self._compare_selected)
        self.select_all_button.clicked.connect(self._select_all_available)
        self.clear_button.clicked.connect(self._clear_selection)
        self.rollback_button.clicked.connect(self._on_rollback_clicked)
        self.snapshot_list.itemSelectionChanged.connect(self._on_snapshot_selected)
        self.snapshot_list.doubleClicked.connect(self._compare_selected)

        self._update_controls()

    def _build_snapshot_group(self) -> QGroupBox:
        group = QGroupBox("快照文件")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(6)

        controls = QHBoxLayout()
        self.list_summary = QLabel("尚未找到快照文件")
        self.list_summary.setObjectName("Muted")
        self.list_summary.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.compare_button = QPushButton("对比所选")
        self.compare_button.setObjectName("Primary")
        controls.addWidget(self.list_summary, 1)
        controls.addWidget(self.compare_button)
        layout.addLayout(controls)

        self.snapshot_list = QTableWidget(0, 5)
        self.snapshot_list.setHorizontalHeaderLabels(
            ["时间", "设备型号", "序列号", "项数", "文件"]
        )
        self.snapshot_list.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.snapshot_list.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.snapshot_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.snapshot_list.setAlternatingRowColors(True)
        self.snapshot_list.verticalHeader().setVisible(False)
        header = self.snapshot_list.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.snapshot_list.setMinimumHeight(110)
        layout.addWidget(self.snapshot_list)
        return group

    def _build_compare_group(self) -> QGroupBox:
        group = QGroupBox("对比结果")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(6)

        self.compare_summary = QLabel("选择快照后点击「对比所选」。")
        self.compare_summary.setObjectName("Muted")
        layout.addWidget(self.compare_summary)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["", "项目", "当前值", "快照值", "状态"]
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemChanged.connect(self._on_table_item_changed)
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        self.select_all_button = QPushButton("全选可用")
        self.clear_button = QPushButton("全不选")
        self.rollback_button = QPushButton("回滚选中")
        self.rollback_button.setObjectName("Danger")
        buttons.addWidget(self.select_all_button)
        buttons.addWidget(self.clear_button)
        buttons.addStretch(1)
        buttons.addWidget(self.rollback_button)
        layout.addLayout(buttons)
        return group

    def on_activated(self) -> None:
        self._refresh_snapshots()

    def on_device_changed(self, device: DeviceInfo | None) -> None:
        serial = device.serial if device is not None and device.connected else ""
        if serial == self._serial:
            return
        self._serial = serial
        self._cancel_jobs(include_rollback=True)
        self._snapshot = None
        self._document = None
        self._clear_compare()
        if serial:
            self.device_label.setText(f"当前设备：{serial}")
            self.device_label.setToolTip(serial)
        else:
            self.device_label.setText("当前设备：未选择")
            self.device_label.setToolTip("")
        self._refresh_snapshots()
        self._update_controls()

    def on_deactivated(self) -> None:
        self._cancel_compare()
        self._cancel_capture()

    def shutdown(self) -> None:
        self._closing = True
        self._cancel_jobs(include_rollback=True)

    def snapshot_dir(self) -> Path:
        configured = (self.context.config.snapshot_dir or "").strip()
        if configured:
            return Path(configured)
        return self.context.config_store.root / "data" / "snapshots"

    def _refresh_snapshots(self) -> None:
        directory = self.snapshot_dir()
        entries: list[tuple[Path, DeviceSnapshot]] = []
        failed = 0
        if directory.is_dir():
            for path in directory.glob("*.json"):
                try:
                    document = load_snapshot(path)
                except SnapshotFormatError:
                    failed += 1
                    continue
                for snapshot in document.devices.values():
                    entries.append((path, snapshot))
        entries.sort(key=lambda item: item[1].captured_at, reverse=True)
        self._entries = entries
        self.snapshot_list.setRowCount(0)
        for path, snapshot in entries:
            row = self.snapshot_list.rowCount()
            self.snapshot_list.insertRow(row)
            values = [
                _display_time(snapshot.captured_at),
                snapshot.model or "未知型号",
                snapshot.serial,
                str(len(snapshot.items)),
                path.name,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(str(path))
                if column == 0:
                    item.setData(
                        Qt.ItemDataRole.UserRole,
                        (str(path), snapshot.serial),
                    )
                self.snapshot_list.setItem(row, column, item)
        if entries:
            skipped = f"，{failed} 个文件无法读取" if failed else ""
            self.list_summary.setText(f"共 {len(entries)} 个设备快照{skipped}")
            self.list_summary.setToolTip(str(directory))
        elif failed:
            self.list_summary.setText(f"{failed} 个快照文件无法读取")
            self.list_summary.setToolTip(str(directory))
        else:
            self.list_summary.setText(f"尚未找到快照文件：{directory}")
            self.list_summary.setToolTip(str(directory))
        self._update_controls()

    def _on_snapshot_selected(self) -> None:
        selected = self.snapshot_list.selectedItems()
        if not selected:
            return
        item = self.snapshot_list.item(selected[0].row(), 0)
        data = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not data:
            return
        path_text, serial = data
        snapshot = next(
            (
                candidate
                for entry_path, candidate in self._entries
                if str(entry_path) == path_text and candidate.serial == serial
            ),
            None,
        )
        if snapshot is None:
            return
        self._snapshot = snapshot
        self._document = None
        self.message_label.setText(
            f"已选择 {Path(path_text).name}（{snapshot.serial}），点击「对比所选」查看差异。"
        )
        self._update_controls()

    def _compare_selected(self) -> None:
        if self._snapshot is None:
            self.message_label.setText("请先在快照列表中选择一条记录")
            return
        self._start_compare(self._snapshot)

    def _start_compare(self, snapshot: DeviceSnapshot) -> None:
        if not self._serial:
            self.message_label.setText("请先连接设备")
            self.context.status.error("请先连接设备")
            return
        if self._compare_job is not None:
            return
        try:
            job = self.context.snapshots.compare(self._serial, snapshot)
        except SnapshotDeviceMismatch as exc:
            self.message_label.setText(str(exc))
            self.context.status.error("当前设备不在快照中")
            self._snapshot = None
            self._clear_compare()
            return
        except ValueError as exc:
            self.message_label.setText(str(exc))
            return
        job.setParent(self)
        self._compare_job = job
        self._snapshot = snapshot
        self.message_label.setText(f"正在对比 {len(snapshot.items)} 项配置…")
        self.compare_summary.setText("正在读取当前设备配置…")
        self.compare_button.setEnabled(False)
        job.finished.connect(self._on_compare_finished)
        job.failed.connect(self._on_compare_failed)
        job.start()
        self._update_controls()

    def _on_compare_finished(self, rows: list[CompareRow]) -> None:
        if self.sender() is not self._compare_job:
            return
        self._compare_job = None
        self.show_compare(rows)
        self.context.status.success(f"配置对比完成：{len(rows)} 项")

    def _on_compare_failed(self, message: str) -> None:
        if self.sender() is not self._compare_job:
            return
        self._compare_job = None
        self.message_label.setText(f"对比失败：{message}")
        self.compare_summary.setText(f"对比失败：{message}")
        self.context.status.error(f"配置对比失败：{message}")
        self._update_controls()

    def show_compare(
        self,
        rows: list[CompareRow],
        snapshot: DeviceSnapshot | None = None,
    ) -> None:
        if snapshot is not None:
            self._snapshot = snapshot
        self._rows = list(rows)
        self._row_index = {}
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        disabled_brush = self.palette().brush(
            QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text
        )
        for row in self._rows:
            table_row = self.table.rowCount()
            self.table.insertRow(table_row)
            self._row_index[row.key] = table_row

            check = QTableWidgetItem("")
            flags = Qt.ItemFlag.ItemIsUserCheckable
            if row.available:
                flags |= Qt.ItemFlag.ItemIsEnabled
            check.setFlags(flags)
            check.setCheckState(
                Qt.CheckState.Checked
                if row.available and not row.same
                else Qt.CheckState.Unchecked
            )
            check.setData(Qt.ItemDataRole.UserRole, row)
            self.table.setItem(table_row, 0, check)

            label = f"{row.group} · {row.label}" if row.group else row.label
            values = [
                label,
                _display_value(row.current),
                _display_value(row.desired),
                row.status,
            ]
            tooltip = (
                f"读取：{row.read_command}\n写入：{row.write_command}"
                + (f"\n重置：{row.reset_command}" if row.reset_command else "")
            )
            if row.item is not None and row.item.error:
                tooltip += f"\n读取错误：{row.item.error}"
            for offset, value in enumerate(values, start=1):
                item = QTableWidgetItem(value)
                item.setToolTip(tooltip)
                if not row.available:
                    item.setForeground(disabled_brush)
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.table.setItem(table_row, offset, item)
        self.table.blockSignals(False)

        available = sum(1 for row in self._rows if row.available)
        changed = sum(
            1 for row in self._rows if row.available and not row.same
        )
        unavailable = len(self._rows) - available
        self.compare_summary.setText(
            f"共 {len(self._rows)} 项：可回滚 {available} 项，"
            f"不同 {changed} 项，不可用 {unavailable} 项。"
        )
        if self._rows:
            self.message_label.setText(
                "默认勾选「可用且不同」的项目；不可用项已置灰并跳过。"
            )
        self._update_controls()

    def _clear_compare(self) -> None:
        self._rows = []
        self._row_index = {}
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.table.blockSignals(False)
        self.compare_summary.setText("选择快照后点击「对比所选」。")
        self._update_controls()

    def _on_table_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() == 0:
            self._update_controls()

    def _selected_rows(self) -> list[CompareRow]:
        selected: list[CompareRow] = []
        for row in self._rows:
            table_row = self._row_index.get(row.key)
            if table_row is None:
                continue
            item = self.table.item(table_row, 0)
            if (
                row.available
                and item is not None
                and item.checkState() == Qt.CheckState.Checked
            ):
                selected.append(row)
        return selected

    def _select_all_available(self) -> None:
        self.table.blockSignals(True)
        for row in self._rows:
            table_row = self._row_index.get(row.key)
            if table_row is None or not row.available:
                continue
            item = self.table.item(table_row, 0)
            if item is not None:
                item.setCheckState(Qt.CheckState.Checked)
        self.table.blockSignals(False)
        self._update_controls()

    def _clear_selection(self) -> None:
        self.table.blockSignals(True)
        for row in self._rows:
            table_row = self._row_index.get(row.key)
            if table_row is None:
                continue
            item = self.table.item(table_row, 0)
            if item is not None:
                item.setCheckState(Qt.CheckState.Unchecked)
        self.table.blockSignals(False)
        self._update_controls()

    def _on_rollback_clicked(self) -> None:
        rows = self._selected_rows()
        if not rows:
            self.message_label.setText("请先勾选要回滚的项目")
            self.context.status.error("请先勾选要回滚的项目")
            return
        preview = []
        for row in rows:
            command = row.write_command or row.reset_command or row.key
            try:
                command = command.format(value=row.desired or "null")
            except (KeyError, IndexError):
                pass
            preview.append(f"{row.label}：{command}")
        shown = preview[:12]
        if len(preview) > len(shown):
            shown.append(f"…另有 {len(preview) - len(shown)} 项")
        self.last_confirmation_text = (
            f"将回滚 {len(rows)} 项设置。\n" + "\n".join(shown)
        )
        spec = get_danger(
            "snapshot.rollback",
            command="\n".join(shown),
            count=len(rows),
            detail=(
                f"将按快照恢复 {len(rows)} 项配置；不可用项会被跳过，"
                "部分设置可能需要重启设备才能生效。"
            ),
        )
        self._pending_rollback_rows = rows
        dialog = DangerDialog(spec, self)
        dialog.accepted.connect(self._on_rollback_accepted)
        dialog.finished.connect(self._clear_confirmation_dialog)
        self.danger_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _on_rollback_accepted(self) -> None:
        rows = list(self._pending_rollback_rows)
        self._pending_rollback_rows = []
        self._start_rollback(rows)

    def _clear_confirmation_dialog(self, _result: int = 0) -> None:
        self.danger_dialog = None
        self._pending_rollback_rows = []

    def _start_rollback(self, rows: list[CompareRow]) -> None:
        if not rows or not self._serial or self._rollback_job is not None:
            return
        job = self.context.snapshots.rollback(self._serial, rows)
        job.setParent(self)
        self._rollback_job = job
        self._rollback_rows = list(rows)
        self._rollback_results = []
        for row in rows:
            table_row = self._row_index.get(row.key)
            if table_row is None:
                continue
            status = self.table.item(table_row, 4)
            if status is not None:
                status.setText("等待回滚")
        self.message_label.setText(f"正在回滚 0/{len(rows)} 项…")
        job.item_finished.connect(self._on_rollback_item)
        job.finished.connect(self._on_rollback_finished)
        job.failed.connect(self._on_rollback_failed)
        job.start()
        self._update_controls()

    def _on_rollback_item(self, row: CompareRow, ok: bool, message: str) -> None:
        if self.sender() is not self._rollback_job:
            return
        status_text = "已回滚" if ok else ("已跳过" if "跳过" in message else "失败")
        if not ok and not message:
            status_text = "失败"
        self._rollback_results.append((row.label, ok, message or status_text))
        table_row = self._row_index.get(row.key)
        if table_row is not None:
            item = self.table.item(table_row, 4)
            if item is not None:
                item.setText(status_text)
                item.setToolTip(message or status_text)
        self.message_label.setText(
            f"正在回滚 {len(self._rollback_results)}/{len(self._rollback_rows)} 项…"
        )

    def _on_rollback_finished(self, results) -> None:
        if self.sender() is not self._rollback_job:
            return
        self._rollback_job = None
        rows = list(self._rollback_results)
        success = sum(1 for _label, ok, _message in rows if ok)
        failure = len(rows) - success
        self.message_label.setText(f"回滚完成：成功 {success} 项，失败 {failure} 项")
        self.context.status.success(
            f"配置回滚完成：成功 {success} 项，失败 {failure} 项"
        )
        self._update_controls()
        if rows:
            show_results(self, "配置回滚结果", rows)
        self._ask_reboot()

    def _on_rollback_failed(self, message: str) -> None:
        if self.sender() is not self._rollback_job:
            return
        self._rollback_job = None
        self.message_label.setText(f"回滚失败：{message}")
        self.context.status.error(f"配置回滚失败：{message}")
        self._update_controls()

    def _ask_reboot(self) -> None:
        if self._closing or not self._serial:
            return
        box = QMessageBox(self)
        box.setWindowTitle("是否重启设备")
        box.setText("配置已回滚。部分设置可能需要重启设备才能生效。")
        later = box.addButton("稍后", QMessageBox.ButtonRole.RejectRole)
        now = box.addButton("立即重启", QMessageBox.ButtonRole.AcceptRole)
        box.setDefaultButton(later)
        box.exec()
        if box.clickedButton() is now:
            process = self.context.adb.run(
                self._serial, "reboot", timeout_ms=15000
            )
            self.context.status.info("已发送重启命令")
            self.message_label.setText("已发送重启命令，等待设备重新连接。")
            if process is not None:
                process.finished.connect(
                    lambda result: self.context.device_service.refresh()
                    if getattr(result, "ok", False)
                    else None
                )
        else:
            self.message_label.setText(
                f"回滚完成：成功 {sum(1 for _l, ok, _m in self._rollback_results if ok)} 项，"
                "可稍后重启设备。"
            )

    def _start_capture(self) -> None:
        if not self._serial:
            self.context.status.error("请先连接设备")
            return
        if any(
            job is not None
            for job in (self._capture_job, self._compare_job, self._rollback_job)
        ):
            self.message_label.setText("当前还有任务在执行，请稍后再导出。")
            return
        job = self.context.snapshots.capture(self._serial)
        job.setParent(self)
        self._capture_job = job
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.cancel_button.show()
        self.message_label.setText("正在读取设备配置…")
        job.progress.connect(self._on_capture_progress)
        job.finished.connect(self._on_capture_finished)
        job.failed.connect(self._on_capture_failed)
        job.start()
        self._update_controls()

    def _on_capture_progress(self, done: int, total: int, label: str) -> None:
        if self.sender() is not self._capture_job:
            return
        self.progress_bar.setRange(0, max(1, total))
        self.progress_bar.setValue(done)
        self.progress_bar.setFormat(f"{label} %v/%m")
        self.message_label.setText(f"正在读取：{label}")

    def _on_capture_finished(self, snapshot: DeviceSnapshot) -> None:
        if self.sender() is not self._capture_job:
            return
        self._capture_job = None
        self.progress_bar.hide()
        self.cancel_button.hide()
        self._update_controls()
        self._apply_capture_result(snapshot)

    def _on_capture_failed(self, message: str) -> None:
        if self.sender() is not self._capture_job:
            return
        self._capture_job = None
        self.progress_bar.hide()
        self.cancel_button.hide()
        self.message_label.setText(f"导出失败：{message}")
        self.context.status.error(f"配置导出失败：{message}")
        self._update_controls()

    def _cancel_capture(self) -> None:
        job = self._capture_job
        if job is None:
            return
        self._capture_job = None
        job.cancel()
        self.progress_bar.hide()
        self.cancel_button.hide()
        self.message_label.setText("已取消导出")
        self._update_controls()

    def _apply_capture_result(self, snapshot: DeviceSnapshot) -> None:
        directory = self.snapshot_dir()
        default_path = directory / default_snapshot_name(snapshot.serial)
        target = self.ask_save_path(default_path)
        if not target:
            self.message_label.setText("已取消保存快照")
            return
        path = Path(target)
        document = SnapshotDocument()
        if path.exists():
            try:
                document = load_snapshot(path)
            except SnapshotFormatError:
                document = SnapshotDocument()
        devices = dict(document.devices)
        devices[snapshot.serial] = snapshot
        document = SnapshotDocument(
            schema_version=document.schema_version,
            created_at=document.created_at,
            devices=devices,
        )
        try:
            saved = save_snapshot(document, path)
        except OSError as exc:
            self.message_label.setText(f"保存快照失败：{exc}")
            self.context.status.error(f"保存快照失败：{exc}")
            return
        self.last_saved_path = saved
        self._document = document
        self._snapshot = snapshot
        self.message_label.setText(f"快照已保存：{saved}")
        self.context.status.success(f"配置快照已保存：{saved.name}")
        self._refresh_snapshots()
        for row in range(self.snapshot_list.rowCount()):
            item = self.snapshot_list.item(row, 4)
            if item is not None and item.text() == saved.name:
                self.snapshot_list.selectRow(row)
                break

    def ask_save_path(self, default_path: Path) -> str:
        path, _selected = QFileDialog.getSaveFileName(
            self,
            "保存配置快照",
            str(default_path),
            "快照文件 (*.json)",
        )
        return path

    def ask_open_path(self) -> str:
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "导入配置快照",
            str(self.snapshot_dir()),
            "快照文件 (*.json)",
        )
        return path

    def _import_snapshot(self) -> None:
        path_text = self.ask_open_path()
        if not path_text:
            return
        try:
            document = load_snapshot(path_text)
        except SnapshotFormatError as exc:
            self.message_label.setText(str(exc))
            self.context.status.error(f"导入快照失败：{exc}")
            return
        self._document = document
        if not self._serial:
            self._snapshot = None
            self._clear_compare()
            self.message_label.setText("请先连接设备")
            self.context.status.error("请先连接设备")
            self._update_controls()
            return
        snapshot = document.devices.get(self._serial)
        if snapshot is None:
            self._snapshot = None
            self._clear_compare()
            self.message_label.setText("当前设备不在快照中")
            serials = "、".join(document.devices) or "无设备"
            self.context.status.error(
                f"当前设备不在快照中：快照包含 {serials}"
            )
            self._update_controls()
            return
        self.message_label.setText(f"已导入 {Path(path_text).name}，正在对比…")
        self._start_compare(snapshot)

    def _cancel_compare(self) -> None:
        job = self._compare_job
        if job is None:
            return
        self._compare_job = None
        job.cancel()
        self.compare_summary.setText("对比已取消")

    def _cancel_jobs(self, include_rollback: bool) -> None:
        self._cancel_capture()
        self._cancel_compare()
        if include_rollback:
            job = self._rollback_job
            if job is not None:
                self._rollback_job = None
                job.cancel()
        if self.danger_dialog is not None:
            self.danger_dialog.reject()
            self.danger_dialog = None

    def _update_controls(self) -> None:
        connected = bool(self._serial)
        busy = any(
            job is not None
            for job in (self._capture_job, self._compare_job, self._rollback_job)
        )
        self.export_button.setEnabled(connected and not busy)
        self.import_button.setEnabled(not busy)
        self.refresh_button.setEnabled(not busy)
        self.compare_button.setEnabled(
            connected and self._snapshot is not None and not busy
        )
        selected = self._selected_rows()
        self.rollback_button.setEnabled(bool(selected) and not busy)
        self.select_all_button.setEnabled(bool(self._rows) and not busy)
        self.clear_button.setEnabled(bool(self._rows) and not busy)
        self.cancel_button.setEnabled(self._capture_job is not None)
