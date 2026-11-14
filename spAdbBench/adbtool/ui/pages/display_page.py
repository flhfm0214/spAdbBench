from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...infrastructure.parsers import DeviceInfo
from ...infrastructure.shell_open import open_folder
from ...services.danger import get_danger
from ...services.display import (
    KEY_EVENTS,
    KEY_GROUPS,
    DisplayInfo,
    DisplayService,
    parse_display_info,
    screenshot_destination,
)
from ..page import BasePage
from ..widgets.danger_dialog import confirm_danger


class ImagePreview(QLabel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ScreenshotPreview")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(140)
        self.setWordWrap(True)
        self._source = QPixmap()
        self.clear_image()

    def set_image(self, path: Path | str) -> bool:
        source = QPixmap(str(path))
        if source.isNull():
            self.clear_image()
            return False
        self._source = source
        self.setText("")
        self._render()
        return True

    def clear_image(self) -> None:
        self._source = QPixmap()
        self.clear()
        self.setText("截图后在此预览")

    def _render(self) -> None:
        if self._source.isNull():
            return
        target = self.contentsRect().size()
        if target.width() <= 2 or target.height() <= 2:
            return
        self.setPixmap(
            self._source.scaled(
                target,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._render()


class DisplayPage(BasePage):
    def __init__(self, context) -> None:
        super().__init__(context)
        self.service = DisplayService(context.adb)
        self._serial = ""
        self._loaded_serial = ""
        self._baseline_serial = ""
        self._baseline_density: int | None = None
        self._baseline_size = ""
        self._baseline_size_overridden = False
        self._baseline_density_overridden = False
        self._info_process = None
        self._action_process = None
        self._screenshot_process = None
        self._last_screenshot: Path | None = None
        self._auto_screenshot_path = True
        self._action_widgets: list = []
        self._key_buttons: dict[str, QPushButton] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        page_layout = QVBoxLayout(content)
        page_layout.setContentsMargins(24, 18, 24, 18)
        page_layout.setSpacing(10)
        scroll.setWidget(content)
        layout.addWidget(scroll)
        layout = page_layout

        header = QHBoxLayout()
        heading = QLabel("屏幕与按键")
        heading.setObjectName("SectionTitle")
        self.message_label = QLabel("选择设备后读取显示参数。")
        self.message_label.setObjectName("Muted")
        self.refresh_button = QPushButton("刷新参数")
        header.addWidget(heading)
        header.addSpacing(12)
        header.addWidget(self.message_label, 1)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        layout.addWidget(self._build_display_group())
        layout.addWidget(self._build_key_group())
        layout.addWidget(self._build_screenshot_group(), 1)

        self.refresh_button.clicked.connect(self._refresh_info)
        self.set_size_button.clicked.connect(self._set_size)
        self.reset_size_button.clicked.connect(self._restore_size)
        self.set_density_button.clicked.connect(self._set_density)
        self.reset_density_button.clicked.connect(self._restore_density)
        self.capture_button.clicked.connect(self._capture)
        self.browse_button.clicked.connect(self._browse_screenshot)
        self.screenshot_path.textEdited.connect(self._mark_manual_screenshot_path)
        self.open_button.clicked.connect(self._open_screenshot)
        self.open_folder_button.clicked.connect(self._open_folder)

        self._update_controls()

    @property
    def key_buttons(self) -> dict[str, QPushButton]:
        return self._key_buttons

    def on_activated(self) -> None:
        self._set_device(self.context.current_device, refresh=True)

    def on_device_changed(self, device: DeviceInfo | None) -> None:
        self._set_device(device, refresh=True)

    def on_deactivated(self) -> None:
        if self._info_process is not None and self._info_process.is_running:
            self._info_process.cancel()
        self._info_process = None

    def _set_device(self, device: DeviceInfo | None, refresh: bool) -> None:
        serial = device.serial if device and device.connected else ""
        if serial == self._serial:
            if refresh and serial and self._loaded_serial != serial:
                self._refresh_info()
            return

        self._serial = serial
        if self._info_process is not None and self._info_process.is_running:
            self._info_process.cancel()
        self._info_process = None
        self._loaded_serial = ""
        self._baseline_serial = ""
        self._baseline_density = None
        self._baseline_size = ""
        self._baseline_size_overridden = False
        self._baseline_density_overridden = False
        self._last_screenshot = None
        self.preview.clear_image()
        self.screenshot_status.setText("尚未截图")
        self.current_size_value.setText("—")
        self.physical_size_value.setText("—")
        self.current_density_value.setText("—")
        self.physical_density_value.setText("—")
        self.baseline_label.setText("初始值：—")

        if serial:
            self.message_label.setText(f"当前设备：{serial}")
            self._auto_screenshot_path = True
            self.screenshot_path.setText(
                str(screenshot_destination(serial, self.context.config.screenshot_dir))
            )
        else:
            self.message_label.setText("未选择设备。")
            self.screenshot_path.clear()

        self._update_controls()
        if refresh and serial and self.isVisible():
            self._refresh_info()

    def _build_display_group(self) -> QGroupBox:
        group = QGroupBox("显示参数")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(0, 8, 0, 4)
        layout.setSpacing(10)

        info_grid = QGridLayout()
        info_grid.setHorizontalSpacing(8)
        info_grid.setVerticalSpacing(4)

        self.current_size_value = QLabel("—")
        self.current_size_value.setObjectName("Value")
        self.physical_size_value = QLabel("—")
        self.physical_size_value.setObjectName("Muted")
        self.current_density_value = QLabel("—")
        self.current_density_value.setObjectName("Value")
        self.physical_density_value = QLabel("—")
        self.physical_density_value.setObjectName("Muted")

        self._add_info_pair(
            info_grid, 0, 0, "当前分辨率", self.current_size_value
        )
        self._add_info_pair(
            info_grid, 0, 2, "物理分辨率", self.physical_size_value
        )
        self._add_info_pair(info_grid, 1, 0, "当前 DPI", self.current_density_value)
        self._add_info_pair(
            info_grid, 1, 2, "物理 DPI", self.physical_density_value
        )
        info_grid.setColumnStretch(1, 1)
        info_grid.setColumnStretch(3, 1)
        info_grid.setColumnStretch(4, 1)
        layout.addLayout(info_grid)

        controls = QVBoxLayout()
        controls.setSpacing(10)

        size_row = QHBoxLayout()
        size_row.setSpacing(10)
        self.width_spin = QSpinBox()
        self.width_spin.setRange(200, 10000)
        self.width_spin.setValue(1080)
        self.width_spin.setToolTip("宽度范围 200–10000 px")
        self.height_spin = QSpinBox()
        self.height_spin.setRange(200, 10000)
        self.height_spin.setValue(2400)
        self.height_spin.setToolTip("高度范围 200–10000 px")
        size_row.addWidget(QLabel("分辨率"))
        size_row.addWidget(self.width_spin)
        size_row.addWidget(QLabel("×"))
        size_row.addWidget(self.height_spin)
        size_row.addWidget(QLabel("px（上限 10000）"))
        size_row.addStretch(1)
        controls.addLayout(size_row)

        density_row = QHBoxLayout()
        density_row.setSpacing(10)
        self.density_spin = QSpinBox()
        self.density_spin.setRange(72, 1000)
        self.density_spin.setValue(420)
        self.density_spin.setToolTip("DPI 范围 72–1000")
        density_row.addWidget(QLabel("密度"))
        density_row.addWidget(self.density_spin)
        density_row.addWidget(QLabel("DPI（上限 1000）"))
        density_row.addStretch(1)
        controls.addLayout(density_row)

        buttons_row = QGridLayout()
        buttons_row.setHorizontalSpacing(10)
        buttons_row.setVerticalSpacing(10)
        self.set_size_button = QPushButton("修改分辨率")
        self.reset_size_button = QPushButton("恢复初始分辨率")
        self.set_density_button = QPushButton("修改 DPI")
        self.reset_density_button = QPushButton("恢复初始 DPI")
        buttons_row.addWidget(self.set_size_button, 0, 0)
        buttons_row.addWidget(self.reset_size_button, 0, 1)
        buttons_row.addWidget(self.set_density_button, 1, 0)
        buttons_row.addWidget(self.reset_density_button, 1, 1)
        buttons_row.setColumnStretch(2, 1)
        controls.addLayout(buttons_row)

        layout.addLayout(controls)

        self.baseline_label = QLabel("初始值：—")
        self.baseline_label.setObjectName("Muted")
        layout.addWidget(self.baseline_label)

        self._action_widgets.extend(
            [
                self.set_size_button,
                self.reset_size_button,
                self.set_density_button,
                self.reset_density_button,
            ]
        )
        return group

    @staticmethod
    def _add_info_pair(
        grid: QGridLayout,
        row: int,
        column: int,
        label: str,
        value: QLabel,
    ) -> None:
        name = QLabel(label)
        name.setObjectName("Muted")
        grid.addWidget(name, row, column)
        grid.addWidget(value, row, column + 1)

    def _build_key_group(self) -> QGroupBox:
        group = QGroupBox("按键")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(4)

        for key_group in KEY_GROUPS:
            row = QHBoxLayout()
            row.setSpacing(4)
            label = QLabel(key_group)
            label.setObjectName("Muted")
            label.setFixedWidth(76)
            row.addWidget(label)
            for key, event in KEY_EVENTS.items():
                if event.group != key_group:
                    continue
                button = QPushButton(event.label)
                tooltip = f"发送按键：{event.label}（KEYCODE {event.code}）"
                if key == "power":
                    tooltip += "；会切换屏幕电源状态"
                elif key == "sleep":
                    tooltip += "；会关闭屏幕"
                elif key == "wakeup":
                    tooltip += "；会唤醒屏幕"
                button.setToolTip(tooltip)
                button.clicked.connect(lambda _checked=False, k=key: self._send_key(k))
                self._key_buttons[key] = button
                self._action_widgets.append(button)
                row.addWidget(button)
            row.addStretch(1)
            layout.addLayout(row)

        note = QLabel("电源、休眠、唤醒会改变设备屏幕状态。")
        note.setObjectName("Muted")
        layout.addWidget(note)
        return group

    def _build_screenshot_group(self) -> QGroupBox:
        group = QGroupBox("截图")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(6)

        path_row = QHBoxLayout()
        self.screenshot_path = QLineEdit()
        self.screenshot_path.setPlaceholderText("截图保存路径")
        self.browse_button = QPushButton("浏览")
        self.capture_button = QPushButton("截取屏幕")
        self.capture_button.setObjectName("Primary")
        path_row.addWidget(QLabel("保存到"))
        path_row.addWidget(self.screenshot_path, 1)
        path_row.addWidget(self.browse_button)
        path_row.addWidget(self.capture_button)

        self.preview = ImagePreview()
        footer = QHBoxLayout()
        self.screenshot_status = QLabel("尚未截图")
        self.screenshot_status.setObjectName("Muted")
        self.open_button = QPushButton("打开截图")
        self.open_folder_button = QPushButton("打开目录")
        footer.addWidget(self.screenshot_status, 1)
        footer.addWidget(self.open_button)
        footer.addWidget(self.open_folder_button)

        layout.addLayout(path_row)
        layout.addWidget(self.preview, 1)
        layout.addLayout(footer)

        self._action_widgets.append(self.capture_button)
        return group

    def _update_controls(self) -> None:
        ready = bool(self._serial)
        info_busy = self._info_process is not None and self._info_process.is_running
        action_busy = self._action_process is not None and self._action_process.is_running
        shot_busy = (
            self._screenshot_process is not None and self._screenshot_process.is_running
        )

        for widget in self._action_widgets:
            widget.setEnabled(ready and not info_busy and not action_busy)
        self.refresh_button.setEnabled(ready and not info_busy and not action_busy)
        self.screenshot_path.setEnabled(ready and not shot_busy)
        self.browse_button.setEnabled(ready and not shot_busy)
        self.capture_button.setEnabled(ready and not shot_busy)
        self.open_button.setEnabled(
            ready and not shot_busy and self._last_screenshot is not None
        )
        self.open_folder_button.setEnabled(
            ready and not shot_busy and self._last_screenshot is not None
        )

    def _refresh_info(self) -> None:
        if not self._serial:
            return
        if self._info_process is not None and self._info_process.is_running:
            return
        serial = self._serial
        process = self.service.info(serial)
        self._info_process = process
        self._update_controls()
        process.finished.connect(
            lambda result, s=serial: self._on_info_finished(s, result)
        )

    def _on_info_finished(self, serial: str, result) -> None:
        if serial != self._serial:
            return
        self._info_process = None
        if result.cancelled:
            self._update_controls()
            return
        if not result.ok:
            self._update_controls()
            self.context.status.error(
                f"读取显示参数失败：{(result.stderr or result.stdout).strip() or '未知错误'}"
            )
            return

        info = parse_display_info(result.stdout)
        if not info.effective_size and info.effective_density is None:
            self._update_controls()
            self.context.status.error("未读取到显示参数")
            return
        self._apply_info(info)
        self._loaded_serial = serial
        self._update_controls()

    def _apply_info(self, info: DisplayInfo) -> None:
        size_text = info.effective_size or "未知"
        if info.size_overridden:
            size_text += "（覆盖）"
        density_text = (
            str(info.effective_density) if info.effective_density is not None else "未知"
        )
        if info.density_overridden:
            density_text += "（覆盖）"
        self.current_size_value.setText(size_text)
        self.physical_size_value.setText(info.physical_size or "—")
        self.current_density_value.setText(density_text)
        self.physical_density_value.setText(
            str(info.physical_density)
            if info.physical_density is not None
            else "—"
        )
        if self._baseline_serial != self._serial or not self._baseline_size:
            self._baseline_serial = self._serial
            self._baseline_size = info.effective_size
            self._baseline_density = info.effective_density
            self._baseline_size_overridden = info.size_overridden
            self._baseline_density_overridden = info.density_overridden
            baseline_parts = []
            if self._baseline_size:
                baseline_parts.append(self._baseline_size)
            if self._baseline_density is not None:
                baseline_parts.append(f"{self._baseline_density} DPI")
            baseline_text = (
                "初始值：" + " · ".join(baseline_parts)
                if baseline_parts
                else "初始值：—"
            )
            self.baseline_label.setText(baseline_text)

        width_text, _, height_text = info.effective_size.partition("x")
        try:
            width = int(width_text)
            height = int(height_text)
        except ValueError:
            pass
        else:
            self.width_spin.blockSignals(True)
            self.height_spin.blockSignals(True)
            self.width_spin.setValue(width)
            self.height_spin.setValue(height)
            self.width_spin.blockSignals(False)
            self.height_spin.blockSignals(False)
        if info.effective_density is not None:
            self.density_spin.blockSignals(True)
            self.density_spin.setValue(info.effective_density)
            self.density_spin.blockSignals(False)

    def _require_device(self) -> bool:
        if not self._serial:
            self.context.status.error("请先连接设备")
            return False
        return True

    def _set_size(self) -> None:
        if not self._require_device():
            return
        width = self.width_spin.value()
        height = self.height_spin.value()
        command = f"adb -s {self._serial} shell wm size {width}x{height}"
        detail = f"当前：{self.current_size_value.text()}；目标：{width}x{height}"
        if not confirm_danger(
            self,
            get_danger("display.set_size", command=command, detail=detail),
        ):
            return
        try:
            process = self.service.set_size(self._serial, width, height)
        except ValueError as exc:
            self.context.status.error(str(exc))
            return
        self._run_action(process, "修改分辨率", refresh=True)

    def _restore_size(self) -> None:
        if not self._require_device():
            return
        if self._loaded_serial != self._serial:
            self.context.status.error("请先刷新显示参数")
            return
        if not self._baseline_size_overridden:
            try:
                process = self.service.reset_size(self._serial)
            except ValueError as exc:
                self.context.status.error(str(exc))
                return
            self._run_action(process, "恢复初始分辨率", refresh=True)
            return
        width_text, _, height_text = self._baseline_size.partition("x")
        try:
            width = int(width_text)
            height = int(height_text)
        except ValueError:
            self.context.status.error("尚未读取到初始分辨率")
            return
        try:
            process = self.service.set_size(self._serial, width, height)
        except ValueError as exc:
            self.context.status.error(str(exc))
            return
        self._run_action(process, "恢复初始分辨率", refresh=True)

    def _set_density(self) -> None:
        if not self._require_device():
            return
        density = self.density_spin.value()
        command = f"adb -s {self._serial} shell wm density {density}"
        detail = f"当前：{self.current_density_value.text()}；目标：{density}"
        if not confirm_danger(
            self,
            get_danger("display.set_density", command=command, detail=detail),
        ):
            return
        try:
            process = self.service.set_density(self._serial, density)
        except ValueError as exc:
            self.context.status.error(str(exc))
            return
        self._run_action(process, "修改 DPI", refresh=True)

    def _restore_density(self) -> None:
        if not self._require_device():
            return
        if self._loaded_serial != self._serial:
            self.context.status.error("请先刷新显示参数")
            return
        if not self._baseline_density_overridden:
            try:
                process = self.service.reset_density(self._serial)
            except ValueError as exc:
                self.context.status.error(str(exc))
                return
            self._run_action(process, "恢复初始 DPI", refresh=True)
            return
        if self._baseline_density is None:
            self.context.status.error("尚未读取到初始 DPI")
            return
        try:
            process = self.service.set_density(self._serial, self._baseline_density)
        except ValueError as exc:
            self.context.status.error(str(exc))
            return
        self._run_action(process, "恢复初始 DPI", refresh=True)

    def _send_key(self, key: str) -> None:
        if not self._require_device():
            return
        try:
            process = self.service.send_key(self._serial, key)
        except ValueError as exc:
            self.context.status.error(str(exc))
            return
        self._run_action(process, f"发送按键：{KEY_EVENTS[key].label}")

    def _run_action(self, process, label: str, refresh: bool = False) -> None:
        serial = self._serial
        self._action_process = process
        self._update_controls()
        self.context.status.info(f"{label}…")
        process.finished.connect(
            lambda result, s=serial, l=label, r=refresh: self._on_action_finished(
                s, l, r, result
            )
        )

    def _on_action_finished(self, serial: str, label: str, refresh: bool, result) -> None:
        if serial != self._serial:
            return
        self._action_process = None
        if result.cancelled:
            self._update_controls()
            return
        if not result.ok:
            self._update_controls()
            self.context.status.error(
                f"{label}失败：{(result.stderr or result.stdout).strip() or '未知错误'}"
            )
            return
        self.context.status.success(f"{label}完成")
        if refresh:
            self._loaded_serial = ""
            self._refresh_info()
        self._update_controls()

    def _browse_screenshot(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self,
            "保存截图",
            self.screenshot_path.text(),
            "PNG (*.png)",
        )
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        self._auto_screenshot_path = False
        self.screenshot_path.setText(path)

    def _mark_manual_screenshot_path(self, _text: str) -> None:
        self._auto_screenshot_path = False

    def _capture(self) -> None:
        if not self._require_device():
            return
        text = self.screenshot_path.text().strip()
        if not text or self._auto_screenshot_path:
            text = str(
                screenshot_destination(self._serial, self.context.config.screenshot_dir)
            )
        path = Path(text)
        if path.suffix.lower() != ".png":
            path = path.with_suffix(".png")
        self.screenshot_path.setText(str(path))
        try:
            process = self.service.screenshot(self._serial, path)
        except (OSError, ValueError) as exc:
            self.context.status.error(f"截图失败：{exc}")
            return

        serial = self._serial
        self._screenshot_process = process
        self._last_screenshot = None
        self.screenshot_status.setText("正在截图…")
        self._update_controls()
        self.context.status.info("正在截取屏幕…")
        process.finished.connect(
            lambda result, s=serial, p=path: self._on_screenshot_finished(s, p, result)
        )

    def _on_screenshot_finished(self, serial: str, path: Path, result) -> None:
        if serial != self._serial:
            return
        self._screenshot_process = None
        if result.cancelled:
            self._update_controls()
            return
        if not result.ok:
            if path.exists() and path.stat().st_size == 0:
                path.unlink(missing_ok=True)
            self.screenshot_status.setText("截图失败")
            self._update_controls()
            self.context.status.error(
                f"截图失败：{(result.stderr or result.stdout).strip() or '未知错误'}"
            )
            return
        if not path.exists() or path.stat().st_size == 0:
            self.screenshot_status.setText("截图失败：文件为空")
            self._update_controls()
            self.context.status.error("截图失败：未生成图片文件")
            return
        if not self.preview.set_image(path):
            self.screenshot_status.setText("截图失败：无法读取图片")
            self._update_controls()
            self.context.status.error("截图失败：无法读取图片")
            return

        self._last_screenshot = path
        self.screenshot_status.setText(f"已保存：{path.name}")
        self._update_controls()
        self.context.status.success("截图完成")

    def _open_screenshot(self) -> None:
        if self._last_screenshot is None:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._last_screenshot)))

    def _open_folder(self) -> None:
        if self._last_screenshot is None:
            return
        folder = self._last_screenshot.parent
        if not open_folder(folder):
            self.context.status.error(f"无法打开截图文件夹：{folder}")
