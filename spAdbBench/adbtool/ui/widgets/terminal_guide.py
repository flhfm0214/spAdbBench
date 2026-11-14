from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)


GUIDE_ITEMS = (
    (
        "ADB 模式",
        "输入 adb 子命令，按 Enter 执行。",
    ),
    (
        "Shell 模式",
        "保持长驻 shell，适合连续执行 pm、am、dumpsys 等命令。",
    ),
    (
        "Fastboot 模式",
        "设备进入 bootloader / fastboot 后自动切换；未连接也可手动选择。",
    ),
    (
        "补全与历史",
        "Tab 补全；管道后按 Tab 补全下一段命令，内置 grep、sed、awk、sort、uniq、head、tail、wc、xargs 等 Linux 管道工具；↑↓ 浏览历史；Ctrl+C 中断，Ctrl+L 清屏。",
    ),
    (
        "命令速查",
        "搜索命令，双击填入输入框。",
    ),
    (
        "连接提示",
        "无设备时显示等待提示；切换设备不会清空已有输出。",
    ),
)


class TerminalGuideDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("终端使用指南")
        self.resize(580, 480)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)

        heading = QLabel("终端使用指南")
        heading.setObjectName("SectionTitle")
        subtitle = QLabel("按 F1 随时打开。")
        subtitle.setObjectName("Muted")
        layout.addWidget(heading)
        layout.addWidget(subtitle)

        self.list = QListWidget()
        self.list.setObjectName("GuideList")
        self.list.setWordWrap(True)
        self.list.setSpacing(2)
        self.list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for title, body in GUIDE_ITEMS:
            item = QListWidgetItem()
            card, body_label = self._build_item(title, body)
            metrics = QFontMetrics(body_label.font())
            text_rect = metrics.boundingRect(
                QRect(0, 0, 460, 1000),
                Qt.TextFlag.TextWordWrap,
                body,
            )
            item.setSizeHint(QSize(500, max(62, text_rect.height() + 56)))
            self.list.addItem(item)
            self.list.setItemWidget(item, card)
        layout.addWidget(self.list, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        buttons.clicked.connect(self.accept)
        layout.addWidget(buttons)

    @staticmethod
    def _build_item(title: str, body: str) -> tuple[QWidget, QLabel]:
        card = QWidget()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(4)
        title_label = QLabel(title)
        title_label.setObjectName("Value")
        body_label = QLabel(body)
        body_label.setObjectName("Muted")
        body_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(body_label)
        return card, body_label
