from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...infrastructure.parsers import DeviceInfo
from ...services.danger import get_danger
from ...services.script import ScriptJob, ScriptLineResult, ScriptRunResult
from ..page import BasePage
from ..widgets.danger_dialog import confirm_danger
from ..widgets.result_dialog import show_text


KIND_LABELS = {
    "echo": "输出",
    "command": "命令",
    "unsupported": "不支持",
    "info": "信息",
}

MAX_RESULT_ROWS = 2000


class ScriptPage(BasePage):
    def __init__(self, context) -> None:
        super().__init__(context)
        self.job_factory = ScriptJob
        self._serial = ""
        self._job = None
        self._running = False
        self._source_path: Path | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(8)

        header = QHBoxLayout()
        heading = QLabel("脚本")
        heading.setObjectName("SectionTitle")
        self.message_label = QLabel("按行执行 ADB 命令。")
        self.message_label.setObjectName("Muted")
        self.status_label = QLabel("未连接设备")
        self.status_label.setObjectName("Muted")
        header.addWidget(heading)
        header.addSpacing(12)
        header.addWidget(self.message_label, 1)
        header.addWidget(self.status_label)
        layout.addLayout(header)

        toolbar = QHBoxLayout()
        self.import_button = QPushButton("导入脚本")
        self.export_button = QPushButton("导出脚本")
        self.run_button = QPushButton("运行脚本")
        self.run_button.setObjectName("Primary")
        self.stop_button = QPushButton("停止")
        self.clear_button = QPushButton("清空结果")
        toolbar.addWidget(self.import_button)
        toolbar.addWidget(self.export_button)
        toolbar.addWidget(self.run_button)
        toolbar.addWidget(self.stop_button)
        toolbar.addWidget(self.clear_button)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._build_editor())
        splitter.addWidget(self._build_results())
        splitter.setSizes([330, 250])
        layout.addWidget(splitter, 1)

        self.import_button.clicked.connect(self._import)
        self.export_button.clicked.connect(self._export)
        self.run_button.clicked.connect(self._start)
        self.stop_button.clicked.connect(self._stop)
        self.clear_button.clicked.connect(self._clear_results)
        self.table.cellDoubleClicked.connect(self._show_result_detail)
        self._update_controls()

    def _build_editor(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        label = QLabel("脚本内容")
        label.setObjectName("Muted")
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(
            "@echo off\n"
            "rem 只执行 adb 开头的行\n"
            "echo 开始检查设备\n"
            "adb shell getprop ro.product.model\n"
            "timeout /t 2\n"
        )
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(label)
        layout.addWidget(self.editor, 1)
        return panel

    def _build_results(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(4)
        label = QLabel("执行结果（双击任意一行查看完整内容）")
        label.setObjectName("Muted")
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["行", "类型", "内容", "输出"])
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
        layout.addWidget(label)
        layout.addWidget(self.table, 1)
        return panel

    def on_activated(self) -> None:
        self._update_controls()

    def on_device_changed(self, device: DeviceInfo | None) -> None:
        serial = device.serial if device and device.connected else ""
        if serial != self._serial and self._running:
            self._stop()
        self._serial = serial
        if serial:
            self.message_label.setText(f"当前设备：{serial}")
        else:
            self.message_label.setText("未选择设备。")
        self._update_controls()

    def shutdown(self) -> None:
        if self._running:
            self._stop()
        if self._job is not None:
            self._job.wait(1500)

    def _confirm(self, spec) -> bool:
        return confirm_danger(self, spec)

    def _start(self) -> None:
        if not self._serial:
            self.context.status.error("请先连接设备")
            return
        if self._running:
            return
        source = self.editor.toPlainText()
        if not source.strip():
            self.message_label.setText("脚本内容为空。")
            self.context.status.error("脚本内容为空")
            return
        name = self._source_path.name if self._source_path else "未命名脚本"
        lines = len(source.splitlines())
        spec = get_danger(
            "script.run",
            command="逐行执行脚本中以 adb 开头的命令",
            detail=(
                f"脚本：{name}\n行数：{lines}\n设备：{self._serial}\n"
                "本地命令会被跳过。"
            ),
        )
        if not self._confirm(spec):
            return

        self._clear_results()
        job = self.job_factory(
            str(self.context.adb.adb_path),
            self._serial,
            source,
        )
        self._job = job
        job.line.connect(self._append_result)
        job.finished.connect(self._on_finished)
        job.state.connect(self._on_state)
        self._running = True
        self._update_controls()
        job.start()

    def _stop(self) -> None:
        if self._job is not None and self._running:
            self._job.cancel()

    def _on_state(self, state: str) -> None:
        self.status_label.setText(state)
        if state in {"已完成", "执行失败", "已停止"}:
            self._running = False
        self._update_controls()

    def _on_finished(self, result: ScriptRunResult) -> None:
        self._running = False
        if result.cancelled:
            self.status_label.setText(f"已停止（{len(result.executed_commands)} 条命令）")
            self.context.status.info("脚本已停止")
        elif result.error:
            self.status_label.setText("执行失败")
            self.context.status.error(f"脚本失败：{result.error}")
        elif result.exit_code != 0:
            self.status_label.setText(f"执行失败（退出码 {result.exit_code}）")
            self.context.status.error(
                f"脚本执行失败，退出码 {result.exit_code}"
            )
        else:
            self.status_label.setText(
                f"已完成（{len(result.executed_commands)} 条 adb 命令）"
            )
            self.context.status.success("脚本执行完成")
        self._update_controls()

    def _append_result(self, item: ScriptLineResult) -> None:
        if self.table.rowCount() >= MAX_RESULT_ROWS:
            self.table.removeRow(0)
        row = self.table.rowCount()
        self.table.insertRow(row)
        values = [
            str(item.line_no),
            KIND_LABELS.get(item.kind, item.kind),
            item.text,
            item.output,
        ]
        for column, value in enumerate(values):
            cell = QTableWidgetItem(value)
            cell.setToolTip(value)
            if not item.ok:
                cell.setForeground(Qt.GlobalColor.red)
            self.table.setItem(row, column, cell)
        self.table.scrollToBottom()

    def _result_detail_text(self, row: int) -> str:
        values = []
        for column in range(self.table.columnCount()):
            item = self.table.item(row, column)
            values.append(item.text() if item is not None else "")
        line_no, kind, content, output = values
        return (
            f"行：{line_no}\n"
            f"类型：{kind}\n\n"
            f"内容：\n{content or '—'}\n\n"
            f"输出：\n{output or '（无输出）'}"
        )

    def _show_result_detail(self, row: int, _column: int) -> None:
        if not 0 <= row < self.table.rowCount():
            return
        show_text(self, "执行结果详情", self._result_detail_text(row))

    def _clear_results(self) -> None:
        self.table.setRowCount(0)

    def _import(self) -> None:
        if self._running:
            return
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "导入脚本",
            "",
            "脚本 (*.bat *.cmd *.txt);;所有文件 (*)",
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                text = Path(path).read_text(encoding="gbk")
            except (OSError, UnicodeDecodeError) as exc:
                self.context.status.error(f"读取脚本失败：{exc}")
                return
        except OSError as exc:
            self.context.status.error(f"读取脚本失败：{exc}")
            return
        self.editor.setPlainText(text)
        self._source_path = Path(path)
        self.message_label.setText(f"已导入：{self._source_path.name}")
        self.context.status.success("脚本已导入")

    def _export(self) -> None:
        if self._running:
            return
        default = self._source_path.name if self._source_path else "adbtool-script.bat"
        path, _filter = QFileDialog.getSaveFileName(
            self,
            "导出脚本",
            str(self.context.config.save_root / default),
            "批处理 (*.bat);;所有文件 (*)",
        )
        if not path:
            return
        try:
            Path(path).write_text(self.editor.toPlainText(), encoding="utf-8")
        except OSError as exc:
            self.context.status.error(f"导出脚本失败：{exc}")
            return
        self._source_path = Path(path)
        self.context.status.success("脚本已导出")

    def _update_controls(self) -> None:
        connected = bool(self._serial)
        self.import_button.setEnabled(not self._running)
        self.export_button.setEnabled(not self._running)
        self.run_button.setEnabled(connected and not self._running)
        self.stop_button.setEnabled(self._running)
        self.editor.setReadOnly(self._running)
