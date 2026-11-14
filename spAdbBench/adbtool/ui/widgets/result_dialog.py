from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class ResultDialog(QDialog):
    def __init__(
        self,
        title: str,
        rows: list[tuple[str, bool, str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.title = title
        self.rows = rows
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(680, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        success = sum(1 for _label, ok, _message in rows if ok)
        failure = len(rows) - success
        summary = QLabel(f"成功 {success} 项，失败 {failure} 项")
        summary.setObjectName("SectionTitle")
        layout.addWidget(summary)

        self.table = QTableWidget(len(rows), 3)
        self.table.setHorizontalHeaderLabels(["对象", "结果", "说明"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for row, (label, ok, message) in enumerate(rows):
            self.table.setItem(row, 0, QTableWidgetItem(label))
            result_item = QTableWidgetItem("成功" if ok else "失败")
            result_item.setData(Qt.ItemDataRole.UserRole, ok)
            self.table.setItem(row, 1, result_item)
            self.table.setItem(row, 2, QTableWidgetItem(message or "—"))
        layout.addWidget(self.table, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        copy_button = QPushButton("复制结果")
        copy_button.clicked.connect(self._copy)
        close_button = QPushButton("关闭")
        close_button.setDefault(True)
        close_button.clicked.connect(self.accept)
        button_row.addWidget(copy_button)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

    def _copy(self) -> None:
        from PySide6.QtWidgets import QApplication

        lines = [self.title]
        for label, ok, message in self.rows:
            lines.append(f"{'成功' if ok else '失败'}\t{label}\t{message}")
        QApplication.clipboard().setText("\n".join(lines))


class TextDialog(QDialog):
    def __init__(self, title: str, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = title
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(760, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        heading = QLabel(title)
        heading.setObjectName("SectionTitle")
        self.text = QPlainTextEdit(text)
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        copy_button = QPushButton("复制全部")
        copy_button.clicked.connect(lambda: self._copy())
        close_button = QPushButton("关闭")
        close_button.setDefault(True)
        close_button.clicked.connect(self.accept)
        button_row.addWidget(copy_button)
        button_row.addWidget(close_button)

        layout.addWidget(heading)
        layout.addWidget(self.text, 1)
        layout.addLayout(button_row)

    def _copy(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self.text.toPlainText())


def show_results(parent: QWidget | None, title: str, rows: list[tuple[str, bool, str]]) -> None:
    ResultDialog(title, rows, parent).exec()


def show_text(parent: QWidget | None, title: str, text: str) -> None:
    TextDialog(title, text, parent).exec()
