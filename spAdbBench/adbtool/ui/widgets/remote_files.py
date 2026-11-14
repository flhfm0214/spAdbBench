from __future__ import annotations

import posixpath

from PySide6.QtCore import QItemSelection, QItemSelectionModel, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...services.remote_files import (
    RemoteEntry,
    RemoteFileService,
    format_size,
    normalize_remote_path,
    parse_ls_output,
)


class _RemoteTable(QTableWidget):
    checkbox_clicked = Signal(int)

    def mousePressEvent(self, event) -> None:
        index = self.indexAt(event.position().toPoint())
        if index.isValid() and index.column() == 0:
            self.checkbox_clicked.emit(index.row())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        index = self.indexAt(event.position().toPoint())
        if index.isValid() and index.column() == 0:
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        index = self.indexAt(event.position().toPoint())
        if index.isValid() and index.column() == 0:
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class RemoteFileDialog(QDialog):
    """`ls -la` based device file and folder picker."""

    def __init__(
        self,
        adb,
        serial: str,
        parent: QWidget | None = None,
        *,
        mode: str = "file",
        start_path: str = "/sdcard",
    ) -> None:
        super().__init__(parent)
        self.service = RemoteFileService(adb)
        self.serial = serial
        self.mode = mode
        self.multi_select = mode != "directory"
        self.current_path = normalize_remote_path(start_path or "/sdcard")
        self.selected_path = ""
        self.selected_paths: list[str] = []
        self._process = None
        self._request_id = 0
        self._closed = False
        self._anchor_row = -1

        self.setWindowTitle("设备文件" if self.multi_select else "选择设备文件夹")
        self.setModal(True)
        self.resize(860, 560)
        self.setMinimumSize(680, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        header = QHBoxLayout()
        heading = QLabel("设备文件")
        heading.setObjectName("SectionTitle")
        self.status_label = QLabel("读取中…")
        self.status_label.setObjectName("Muted")
        self.status_label.setWordWrap(True)
        header.addWidget(heading)
        header.addSpacing(10)
        header.addWidget(self.status_label, 1)
        layout.addLayout(header)

        nav = QHBoxLayout()
        nav.setSpacing(6)
        self.up_button = QPushButton("上级")
        self.refresh_button = QPushButton("刷新")
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("/sdcard")
        self.go_button = QPushButton("转到")
        nav.addWidget(self.up_button)
        nav.addWidget(self.refresh_button)
        nav.addWidget(self.path_edit, 1)
        nav.addWidget(self.go_button)
        layout.addLayout(nav)

        self.table = _RemoteTable(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["选择", "名称", "大小", "修改时间", "权限"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
            if self.multi_select
            else QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(False)
        table_header = self.table.horizontalHeader()
        table_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(0, 46)
        layout.addWidget(self.table, 1)

        footer = QHBoxLayout()
        footer.setSpacing(6)
        self.hint = QLabel(
            "Ctrl/Shift 多选文件和文件夹；双击文件夹进入。"
            if self.multi_select
            else "推送目标只能选择一个文件夹；双击文件夹进入。"
        )
        self.hint.setObjectName("Muted")
        footer.addWidget(self.hint, 1)
        self.choose_current = QPushButton("选择当前文件夹")
        self.choose_selected = QPushButton("选择选中项")
        self.choose_selected.setObjectName("Primary")
        self.cancel_button = QPushButton("取消")
        footer.addWidget(self.choose_current)
        footer.addWidget(self.choose_selected)
        footer.addWidget(self.cancel_button)
        layout.addLayout(footer)

        self._update_action_state()
        self.up_button.clicked.connect(self._go_up)
        self.refresh_button.clicked.connect(lambda: self._load(self.current_path))
        self.go_button.clicked.connect(self._go_path)
        self.path_edit.returnPressed.connect(self._go_path)
        self.table.checkbox_clicked.connect(self._on_checkbox_clicked)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.cellClicked.connect(self._on_cell_clicked)
        self.table.cellDoubleClicked.connect(self._on_double_click)
        self.choose_current.clicked.connect(self._choose_current_folder)
        self.choose_selected.clicked.connect(self._choose_selected_entries)
        self.cancel_button.clicked.connect(self.reject)
        self.rejected.connect(self._stop_listing)
        self._load(self.current_path)

    def _load(self, path: str) -> None:
        path = normalize_remote_path(path)
        self.path_edit.setText(path)
        self.status_label.setText("读取中…")
        self._request_id += 1
        request_id = self._request_id
        process = self._process
        if process is not None and process.is_running:
            process.cancel()
        try:
            process = self.service.list(self.serial, path)
        except ValueError as exc:
            self.status_label.setText(f"读取失败：{exc}")
            return
        self._process = process
        process.finished.connect(
            lambda result, r=request_id, p=path: self._on_listing(r, p, result)
        )

    def _on_listing(self, request_id: int, path: str, result) -> None:
        if request_id != self._request_id or self._closed:
            return
        self._process = None
        if result.cancelled:
            return
        if not result.ok:
            message = (result.stderr or result.stdout or "读取目录失败").strip()
            self.status_label.setText(f"读取失败：{message}")
            return
        if not result.stdout.strip() and result.stderr.strip():
            self.status_label.setText(f"读取失败：{result.stderr.strip()}")
            return
        entries = parse_ls_output(path, result.stdout)
        if not entries and result.stdout.lstrip().startswith("ls:"):
            self.status_label.setText(f"读取失败：{result.stdout.strip()}")
            return
        self.current_path = path
        self._fill_table(entries, path)
        self.status_label.setText(
            f"{len(entries)} 项 · {path}" if entries else f"空文件夹 · {path}"
        )
        self.path_edit.setText(path)
        self.up_button.setEnabled(path != "/")
        self._update_action_state()

    def _fill_table(self, entries: list[RemoteEntry], path: str) -> None:
        self.table.setRowCount(0)
        self._anchor_row = -1
        for entry in entries:
            row = self.table.rowCount()
            self.table.insertRow(row)
            check_item = QTableWidgetItem()
            check_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            check_item.setCheckState(Qt.CheckState.Unchecked)
            self.table.setItem(row, 0, check_item)

            name = entry.name + (f" → {entry.link_target}" if entry.link_target else "")
            name_item = QTableWidgetItem(name)
            name_item.setData(Qt.ItemDataRole.UserRole, entry)
            name_item.setToolTip(entry.path)
            if entry.is_dir:
                name_item.setToolTip(f"{entry.path}\n{entry.mode}")
            self.table.setItem(row, 1, name_item)

            size_item = QTableWidgetItem(format_size(entry.size, entry.is_dir))
            size_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self.table.setItem(row, 2, size_item)

            self.table.setItem(row, 3, QTableWidgetItem(entry.modified))

            permission_item = QTableWidgetItem(entry.mode)
            permission_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            permission_item.setToolTip(
                f"{entry.permissions}  {entry.owner}:{entry.group}"
            )
            self.table.setItem(row, 4, permission_item)
        if self.table.rowCount():
            self.table.selectRow(0)
            self._anchor_row = 0
        self._sync_checks()

    def _entry_at(self, row: int) -> RemoteEntry | None:
        item = self.table.item(row, 1)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _selected_entries(self) -> list[RemoteEntry]:
        rows = sorted(
            {index.row() for index in self.table.selectionModel().selectedRows()}
        )
        entries: list[RemoteEntry] = []
        for row in rows:
            entry = self._entry_at(row)
            if entry is not None:
                entries.append(entry)
        return entries

    def _sync_checks(self) -> None:
        selected = {
            index.row() for index in self.table.selectionModel().selectedRows()
        }
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None:
                continue
            state = (
                Qt.CheckState.Checked
                if row in selected
                else Qt.CheckState.Unchecked
            )
            if item.checkState() != state:
                item.setCheckState(state)

    def _on_selection_changed(self) -> None:
        self._sync_checks()
        self._update_action_state()

    def _on_cell_clicked(self, row: int, column: int) -> None:
        if column == 0:
            return
        if not (QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier):
            self._anchor_row = row

    def _on_checkbox_clicked(self, row: int) -> None:
        modifiers = QApplication.keyboardModifiers()
        selection = self.table.selectionModel()
        model = self.table.model()
        if self.multi_select and modifiers & Qt.KeyboardModifier.ControlModifier:
            selection.select(
                model.index(row, 0),
                QItemSelectionModel.SelectionFlag.Toggle
                | QItemSelectionModel.SelectionFlag.Rows,
            )
            self._anchor_row = row
        elif self.multi_select and modifiers & Qt.KeyboardModifier.ShiftModifier:
            anchor = self._anchor_row if self._anchor_row >= 0 else row
            first, last = sorted((anchor, row))
            item_selection = QItemSelection(
                model.index(first, 0),
                model.index(last, 0),
            )
            selection.select(
                item_selection,
                QItemSelectionModel.SelectionFlag.ClearAndSelect
                | QItemSelectionModel.SelectionFlag.Rows,
            )
        else:
            self.table.clearSelection()
            self.table.selectRow(row)
            self._anchor_row = row
        self._sync_checks()
        self._update_action_state()

    def _update_action_state(self) -> None:
        entries = self._selected_entries()
        allowed = bool(entries) and (
            self.multi_select or all(entry.is_dir for entry in entries)
        )
        self.choose_current.setEnabled(bool(self.current_path))
        self.choose_selected.setEnabled(allowed)
        if len(entries) > 1:
            self.choose_selected.setText(f"选择 {len(entries)} 项")
        else:
            self.choose_selected.setText("选择选中项")

    def _go_up(self) -> None:
        parent = posixpath.dirname(self.current_path.rstrip("/")) or "/"
        self._load(parent)

    def _go_path(self) -> None:
        path = self.path_edit.text().strip()
        if path:
            self._load(path)

    def _on_double_click(self, row: int, column: int) -> None:
        if column == 0:
            return
        entry = self._entry_at(row)
        if entry is None:
            return
        if entry.is_dir:
            self._load(entry.path)
        elif self.multi_select:
            self._accept_paths([entry.path])

    def _choose_current_folder(self) -> None:
        self._accept_paths([self.current_path])

    def _choose_selected_entries(self) -> None:
        entries = self._selected_entries()
        if not entries:
            return
        if self.multi_select:
            self._accept_paths([entry.path for entry in entries])
            return
        folder = next((entry for entry in entries if entry.is_dir), None)
        if folder is not None:
            self._accept_paths([folder.path])

    def _accept_paths(self, paths: list[str]) -> None:
        normalized = [normalize_remote_path(path) for path in paths]
        self.selected_paths = normalized
        self.selected_path = normalized[0] if normalized else ""
        self._stop_listing()
        self.accept()

    def _stop_listing(self) -> None:
        self._closed = True
        process = self._process
        self._process = None
        if process is not None and process.is_running:
            process.cancel()

    def closeEvent(self, event) -> None:
        self._stop_listing()
        super().closeEvent(event)
