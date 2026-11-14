from __future__ import annotations

import json
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...infrastructure.execution_log import ExecutionRecord
from ...infrastructure.shell_open import open_folder
from ..page import BasePage


class LogPage(BasePage):
    def __init__(self, context) -> None:
        super().__init__(context)
        self.log = context.execution_log
        self._history_count = len(self.log.records())
        self._records: list[ExecutionRecord] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(8)

        header = QHBoxLayout()
        heading = QLabel("运行日志")
        heading.setObjectName("SectionTitle")
        self.message_label = QLabel("记录 ADB 命令、输出与耗时。")
        self.message_label.setObjectName("Muted")
        self.message_label.setWordWrap(True)
        header.addWidget(heading)
        header.addSpacing(12)
        header.addWidget(self.message_label, 1)
        layout.addLayout(header)

        notice_row = QHBoxLayout()
        self.notice_label = QLabel()
        self.notice_label.setObjectName("Muted")
        self.notice_label.setWordWrap(True)
        self.open_folder_button = QPushButton("打开日志文件夹")
        self.open_folder_button.setToolTip("打开日志文件所在目录，查看历史日志")
        notice_row.addWidget(self.notice_label, 1)
        notice_row.addWidget(self.open_folder_button)
        layout.addLayout(notice_row)

        toolbar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("筛选设备、命令、输出或错误")
        self.search.setClearButtonEnabled(True)
        self.fail_only = QCheckBox("只看失败")
        self.count_label = QLabel("0 条")
        self.count_label.setObjectName("Muted")
        self.refresh_button = QPushButton("刷新")
        self.clear_button = QPushButton("清空列表")
        self.clear_button.setToolTip("只清空当前表格，不删除日志文件")
        self.export_button = QPushButton("导出")
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(self.fail_only)
        toolbar.addWidget(self.count_label)
        toolbar.addWidget(self.refresh_button)
        toolbar.addWidget(self.clear_button)
        toolbar.addWidget(self.export_button)
        layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._build_table())
        splitter.addWidget(self._build_detail())
        splitter.setSizes([400, 240])
        layout.addWidget(splitter, 1)

        file_row = QHBoxLayout()
        self.file_label = QLabel()
        self.file_label.setObjectName("Muted")
        self.file_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        file_row.addWidget(self.file_label, 1)
        layout.addLayout(file_row)

        self.search.textChanged.connect(self._render)
        self.fail_only.toggled.connect(self._render)
        self.refresh_button.clicked.connect(self._reload)
        self.clear_button.clicked.connect(self._clear_view)
        self.export_button.clicked.connect(self._export)
        self.open_folder_button.clicked.connect(self._open_folder)
        self.copy_command_button.clicked.connect(self._copy_command)
        self.copy_output_button.clicked.connect(self._copy_output)
        self.table.itemSelectionChanged.connect(self._show_selected)
        self.log.record_added.connect(self._on_record_added)

        self._update_file_label()
        self._render()
        self._show_selected()

    def _build_table(self) -> QTableWidget:
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["时间", "设备", "命令", "结果", "耗时"]
        )
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        return self.table

    def _build_detail(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(6)

        label = QLabel("命令详情")
        label.setObjectName("Muted")
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.copy_command_button = QPushButton("复制命令")
        self.copy_output_button = QPushButton("复制输出")
        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(self.copy_command_button)
        footer.addWidget(self.copy_output_button)

        layout.addWidget(label)
        layout.addWidget(self.detail, 1)
        layout.addLayout(footer)
        return panel

    def _matches(self, record: ExecutionRecord) -> bool:
        if self.fail_only.isChecked() and record.ok:
            return False
        text = self.search.text().strip().lower()
        if not text:
            return True
        haystack = " ".join(
            [
                record.serial,
                record.command,
                record.stdout,
                record.stderr,
                record.result_text,
            ]
        ).lower()
        return text in haystack

    def _render(self) -> None:
        self.table.setRowCount(0)
        for record in self._records:
            if self._matches(record):
                self._append_row(record)
        self._update_count()
        if self.table.rowCount() and not self.table.selectedItems():
            self.table.selectRow(self.table.rowCount() - 1)
        self._show_selected()

    def _append_row(self, record: ExecutionRecord) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        started = record.started_at
        time_text = started.split("T", 1)[1][:8] if "T" in started else started
        values = [
            time_text,
            record.serial or "—",
            record.command,
            record.result_text,
            f"{record.duration_ms} ms",
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if column == 0:
                item.setData(Qt.ItemDataRole.UserRole, record)
                item.setToolTip(record.started_at)
            elif column == 2:
                item.setToolTip(record.command)
            self.table.setItem(row, column, item)

    def _update_count(self) -> None:
        total = len(self._records)
        visible = self.table.rowCount()
        self.count_label.setText(f"{visible} / {total} 条")

    def _update_file_label(self) -> None:
        if self.log.path is None:
            self.file_label.setText("日志：仅保存在内存")
            self.notice_label.setText(
                "日志会持续追加保存到磁盘；当前未配置日志文件路径。"
            )
            self.open_folder_button.setEnabled(False)
            return
        self.open_folder_button.setEnabled(True)
        self.notice_label.setText(
            f"日志会持续追加写入 {self.log.path}，关闭后保留；"
            "重新启动只显示本次运行产生的新记录，历史日志仍保存在日志文件夹。"
        )
        suffix = f"（历史 {self._history_count} 条，本次 {len(self._records)} 条）"
        if self.log.last_error:
            suffix += f" 写入失败：{self.log.last_error}"
        self.file_label.setText(f"日志文件：{self.log.path}{suffix}")

    def _on_record_added(self, record: ExecutionRecord) -> None:
        self._records.append(record)
        self._update_file_label()
        if len(self._records) > 2000:
            self._records = self._records[-2000:]
            self._render()
            return
        if not self._matches(record):
            self._update_count()
            return
        at_bottom = (
            self.table.verticalScrollBar().value()
            >= self.table.verticalScrollBar().maximum()
        )
        self._append_row(record)
        self._update_count()
        if at_bottom:
            self.table.scrollToBottom()

    def _reload(self) -> None:
        self._update_file_label()
        self._render()
        self.context.status.info("只显示本次运行产生的日志，历史日志保留在日志文件夹")

    def _clear_view(self) -> None:
        self._records = []
        self.table.setRowCount(0)
        self.detail.clear()
        self._update_count()

    def _selected_record(self) -> ExecutionRecord | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        record = item.data(Qt.ItemDataRole.UserRole)
        return record if isinstance(record, ExecutionRecord) else None

    def _show_selected(self) -> None:
        record = self._selected_record()
        if record is None:
            self.detail.setPlainText("选择一条记录查看完整命令与输出。")
            self.copy_command_button.setEnabled(False)
            self.copy_output_button.setEnabled(False)
            return
        self.copy_command_button.setEnabled(True)
        self.copy_output_button.setEnabled(True)
        lines = [
            f"时间：{record.started_at}",
            f"设备：{record.serial or '—'}",
            f"命令：{record.command}",
            f"结果：{record.result_text}（退出码 {record.exit_code}）",
            f"耗时：{record.duration_ms} ms",
            "",
            "stdout:",
            record.stdout or "（空）",
            "",
            "stderr:",
            record.stderr or "（空）",
        ]
        self.detail.setPlainText("\n".join(lines))

    def _copy_command(self) -> None:
        record = self._selected_record()
        if record is None:
            return
        QApplication.clipboard().setText(record.command)
        self.context.status.success("命令已复制")

    def _copy_output(self) -> None:
        record = self._selected_record()
        if record is None:
            return
        text = record.stdout
        if record.stderr:
            text = f"{text}\n{record.stderr}" if text else record.stderr
        QApplication.clipboard().setText(text)
        self.context.status.success("输出已复制")

    def _export(self) -> None:
        default_name = (
            f"execution-log-{datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl"
        )
        path, _filter = QFileDialog.getSaveFileName(
            self,
            "导出运行日志",
            str(self.context.config.save_root / default_name),
            "JSON Lines (*.jsonl);;所有文件 (*)",
        )
        if not path:
            return
        lines = [
            json.dumps(record.to_dict(), ensure_ascii=False)
            for record in self._records
        ]
        try:
            Path(path).write_text(
                ("\n".join(lines) + "\n") if lines else "",
                encoding="utf-8",
            )
        except OSError as exc:
            self.context.status.error(f"导出失败：{exc}")
            return
        self.context.status.success(f"本次运行日志已导出到 {path}")

    def _open_folder(self) -> None:
        if self.log.path is None:
            self.context.status.error("当前日志仅保存在内存")
            return
        try:
            self.log.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.context.status.error(f"无法创建日志目录：{exc}")
            return
        folder = self.log.path.parent
        if not open_folder(folder):
            self.context.status.error(f"无法打开日志文件夹：{folder}")
