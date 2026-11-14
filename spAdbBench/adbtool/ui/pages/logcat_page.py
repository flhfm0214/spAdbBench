from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ...infrastructure.parsers import DeviceInfo
from ...services.logcat import LogcatSession, LogLine, level_passes
from ..page import BasePage


LEVEL_CHOICES = (
    ("V", "Verbose（全部）"),
    ("D", "Debug"),
    ("I", "Info"),
    ("W", "警告"),
    ("E", "错误"),
    ("F", "致命"),
)

MAX_ROWS = 3000
FLUSH_INTERVAL_MS = 120


class LogcatPage(BasePage):
    def __init__(self, context) -> None:
        super().__init__(context)
        self.session = LogcatSession(context.adb)
        self._serial = ""
        self._running = False
        self._paused = False
        self._pending: list[LogLine] = []
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(FLUSH_INTERVAL_MS)
        self._flush_timer.timeout.connect(self._flush_pending)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(8)

        header = QHBoxLayout()
        heading = QLabel("Logcat")
        heading.setObjectName("SectionTitle")
        self.message_label = QLabel("选择设备后开始实时日志。")
        self.message_label.setObjectName("Muted")
        self.state_label = QLabel("未连接设备")
        self.state_label.setObjectName("Muted")
        header.addWidget(heading)
        header.addSpacing(12)
        header.addWidget(self.message_label, 1)
        header.addWidget(self.state_label)
        layout.addLayout(header)

        filters = QHBoxLayout()
        level_label = QLabel("最低级别")
        level_label.setObjectName("Muted")
        self.level_combo = QComboBox()
        for level, label in LEVEL_CHOICES:
            self.level_combo.addItem(label, level)
        self.keyword_edit = QLineEdit()
        self.keyword_edit.setPlaceholderText("关键字，例如 crash、ANR")
        self.keyword_edit.setClearButtonEnabled(True)
        self.package_edit = QLineEdit()
        self.package_edit.setPlaceholderText("应用包名（可选），按 PID 过滤")
        self.package_edit.setClearButtonEnabled(True)
        filters.addWidget(level_label)
        filters.addWidget(self.level_combo)
        filters.addWidget(self.keyword_edit, 1)
        filters.addWidget(self.package_edit, 1)
        layout.addLayout(filters)

        actions = QHBoxLayout()
        self.start_button = QPushButton("开始")
        self.start_button.setObjectName("Primary")
        self.stop_button = QPushButton("停止")
        self.pause_button = QPushButton("暂停")
        self.clear_button = QPushButton("清空")
        self.export_button = QPushButton("导出")
        actions.addWidget(self.start_button)
        actions.addWidget(self.stop_button)
        actions.addWidget(self.pause_button)
        actions.addWidget(self.clear_button)
        actions.addWidget(self.export_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        status_row = QHBoxLayout()
        self.auto_scroll = QCheckBox("自动滚动")
        self.auto_scroll.setChecked(True)
        self.count_label = QLabel("0 条")
        self.count_label.setObjectName("Muted")
        status_row.addWidget(self.auto_scroll)
        status_row.addWidget(self.count_label)
        status_row.addStretch(1)
        layout.addLayout(status_row)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["时间", "级别", "Tag", "消息"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

        self.start_button.clicked.connect(self._start)
        self.stop_button.clicked.connect(self._stop)
        self.pause_button.clicked.connect(self._toggle_pause)
        self.clear_button.clicked.connect(self._clear)
        self.export_button.clicked.connect(self._export)
        self.level_combo.currentIndexChanged.connect(self._apply_filters)
        self.keyword_edit.textChanged.connect(self._apply_filters)
        self.package_edit.returnPressed.connect(self._start)
        self.session.line.connect(self._on_line)
        self.session.state.connect(self._on_state)
        self.session.error.connect(self._on_error)

        self._update_controls()

    def on_activated(self) -> None:
        self._update_controls()

    def on_deactivated(self) -> None:
        self._flush_pending()

    def shutdown(self) -> None:
        self._stop(clear=True)

    def on_device_changed(self, device: DeviceInfo | None) -> None:
        serial = device.serial if device and device.connected else ""
        if serial != self._serial:
            self._stop(clear=True)
            self._serial = serial
        if not serial:
            self.message_label.setText("未选择设备。")
            self._set_state("未连接设备")
        else:
            self.message_label.setText(f"当前设备：{serial}")
            if not self._running:
                self._set_state("就绪")
        self._update_controls()

    def _start(self) -> None:
        if not self._serial or self._running:
            return
        package = self.package_edit.text().strip()
        self._clear()
        self._running = True
        self._set_state("正在启动…")
        self._update_controls()
        self.session.start(
            self._serial,
            self.level_combo.currentData(),
            self.keyword_edit.text().strip(),
            package,
        )

    def _stop(self, clear: bool = False) -> None:
        if not clear:
            self._flush_pending()
        self.session.stop()
        self._running = False
        self._paused = False
        self.pause_button.setText("暂停")
        if clear:
            self._clear()
        self._set_state("就绪" if self._serial else "未连接设备")
        self._update_controls()

    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        self.pause_button.setText("继续" if self._paused else "暂停")
        self.session.set_paused(self._paused)

    def _apply_filters(self) -> None:
        self.session.set_filters(
            self.level_combo.currentData(),
            self.keyword_edit.text().strip(),
        )

    def _on_state(self, state: str) -> None:
        if state in {"运行中", "已暂停", "正在定位应用进程…"}:
            self._running = True
        elif state == "已停止":
            self._running = False
        if state == "已停止":
            self._paused = False
            self.pause_button.setText("暂停")
        self._set_state(state)
        self._update_controls()

    def _on_error(self, message: str) -> None:
        self.context.status.error(f"Logcat：{message}")

    def _on_line(self, line: LogLine) -> None:
        if self._paused:
            return
        if not level_passes(line.level, self.level_combo.currentData()):
            return
        keyword = self.keyword_edit.text().strip().lower()
        if keyword and keyword not in line.raw.lower():
            return
        self._pending.append(line)
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def _flush_pending(self) -> None:
        self._flush_timer.stop()
        if not self._pending:
            return
        pending = self._pending
        self._pending = []
        self.table.setUpdatesEnabled(False)
        try:
            for line in pending:
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(line.timestamp))
                self.table.setItem(row, 1, QTableWidgetItem(line.level))
                self.table.setItem(row, 2, QTableWidgetItem(line.tag))
                self.table.setItem(row, 3, QTableWidgetItem(line.message))
            excess = self.table.rowCount() - MAX_ROWS
            for _ in range(max(0, excess)):
                self.table.removeRow(0)
        finally:
            self.table.setUpdatesEnabled(True)
        self.count_label.setText(f"{self.table.rowCount()} 条")
        self._update_controls()
        if self.auto_scroll.isChecked():
            self.table.scrollToBottom()

    def _clear(self) -> None:
        self._flush_timer.stop()
        self._pending.clear()
        self.session.clear()
        self.table.setRowCount(0)
        self.count_label.setText("0 条")
        self._update_controls()

    def _export(self) -> None:
        if self.table.rowCount() == 0:
            self.context.status.error("当前没有可导出的日志")
            return
        default_name = f"logcat-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
        path, _filter = QFileDialog.getSaveFileName(
            self,
            "导出 Logcat",
            str(self.context.config.save_root / default_name),
            "日志文件 (*.log);;文本文件 (*.txt);;所有文件 (*)",
        )
        if not path:
            return
        lines = []
        for row in range(self.table.rowCount()):
            parts = [
                self.table.item(row, column).text()
                for column in range(self.table.columnCount())
            ]
            lines.append(f"{parts[0]} {parts[1]} {parts[2]}: {parts[3]}")
        try:
            Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError as exc:
            self.context.status.error(f"导出失败：{exc}")
            return
        self.context.status.success(f"Logcat 已导出到 {path}")

    def _set_state(self, text: str) -> None:
        self.state_label.setText(text)

    def _update_controls(self) -> None:
        ready = bool(self._serial)
        self.start_button.setEnabled(ready and not self._running)
        self.stop_button.setEnabled(self._running)
        self.pause_button.setEnabled(self._running)
        self.clear_button.setEnabled(self.table.rowCount() > 0)
        self.export_button.setEnabled(self.table.rowCount() > 0)
        self.level_combo.setEnabled(ready)
        self.keyword_edit.setEnabled(ready)
        self.package_edit.setEnabled(ready and not self._running)
