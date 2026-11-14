from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...services.danger import DangerSpec


class DangerDialog(QDialog):
    def __init__(self, spec: DangerSpec, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.spec = spec
        self.setObjectName("DangerDialog")
        self.setWindowTitle(spec.title)
        self.setModal(True)
        self.resize(580, 390)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)

        title = QLabel(spec.title)
        title.setObjectName("SectionTitle")
        risk = QLabel(f"风险等级：{spec.risk.value}")
        risk.setObjectName("DangerRisk")

        command_label = QLabel("将执行以下命令")
        command_label.setObjectName("Muted")
        self.command_text = QPlainTextEdit(spec.command)
        self.command_text.setReadOnly(True)
        self.command_text.setMaximumHeight(86)
        self.command_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)

        impact_label = QLabel("影响")
        impact_label.setObjectName("Muted")
        self.impact_text = QLabel(spec.impact)
        self.impact_text.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(risk)
        layout.addWidget(command_label)
        layout.addWidget(self.command_text)
        layout.addWidget(impact_label)
        layout.addWidget(self.impact_text)

        if spec.count is not None:
            count = QLabel(f"受影响对象：{spec.count} 个")
            count.setObjectName("DangerRisk")
            layout.addWidget(count)

        if spec.detail:
            detail = QLabel(spec.detail)
            detail.setObjectName("Muted")
            detail.setWordWrap(True)
            layout.addWidget(detail)

        note = QLabel("请确认命令和影响后再执行。")
        note.setObjectName("Muted")
        layout.addWidget(note)
        layout.addStretch(1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setDefault(True)
        self.cancel_button.setAutoDefault(True)
        self.cancel_button.clicked.connect(self.reject)
        self.confirm_button = QPushButton("执行")
        self.confirm_button.setObjectName("Danger")
        self.confirm_button.setDefault(False)
        self.confirm_button.setAutoDefault(False)
        self.confirm_button.clicked.connect(self.accept)
        button_row.addWidget(self.cancel_button)
        button_row.addWidget(self.confirm_button)
        layout.addLayout(button_row)

        self.cancel_button.setFocus(Qt.FocusReason.OtherFocusReason)

    @property
    def default_button(self) -> QPushButton:
        return self.cancel_button

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.cancel_button.setFocus(Qt.FocusReason.OtherFocusReason)


def confirm_danger(parent: QWidget | None, spec: DangerSpec) -> bool:
    dialog = DangerDialog(spec, parent)
    return dialog.exec() == QDialog.DialogCode.Accepted
