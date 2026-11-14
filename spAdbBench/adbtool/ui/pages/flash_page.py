from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...infrastructure.parsers import DeviceInfo
from ...services.danger import get_danger
from ...services.fastboot import FastbootCommandSession
from ...services.flash import REBOOT_MODES, FlashService
from ..page import BasePage
from ..widgets.danger_dialog import confirm_danger
from ..widgets.result_dialog import show_text


PARTITIONS = ("boot", "init_boot", "recovery", "vbmeta", "vendor_boot", "dtbo")


class FlashPage(BasePage):
    def __init__(self, context) -> None:
        super().__init__(context)
        self.service = FlashService(context.adb)
        self.fastboot_session = FastbootCommandSession(context.adb, self)
        self._serial = ""
        self._fastboot = False
        self._process = None
        self._repair_job = None
        self._closing = False
        self._unlock_output = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(10)
        scroll.setWidget(content)
        root.addWidget(scroll)

        header = QHBoxLayout()
        heading = QLabel("刷机辅助")
        heading.setObjectName("SectionTitle")
        self.device_label = QLabel("当前设备：未选择")
        self.device_label.setObjectName("Muted")
        header.addWidget(heading)
        header.addSpacing(12)
        header.addWidget(self.device_label, 1)
        layout.addLayout(header)

        self.message_label = QLabel("重启与解锁会在确认后执行。")
        self.message_label.setObjectName("Muted")
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label)

        layout.addWidget(self._build_reboot_group())
        layout.addWidget(self._build_unlock_group())
        layout.addWidget(self._build_image_group())
        layout.addWidget(self._build_repair_group())
        layout.addStretch(1)

        self.repair_buttons = (
            self.repair_button,
            self.reconnect_button,
            self.refresh_button,
            self.version_button,
        )
        for button in self.reboot_buttons.values():
            button.clicked.connect(
                lambda _checked=False, b=button: self._reboot(b.property("mode"))
            )
        self.copy_unlock_button.clicked.connect(
            lambda: self._copy_text(self.unlock_command, "解锁命令")
        )
        self.copy_lock_button.clicked.connect(
            lambda: self._copy_text(self.lock_command, "回锁命令")
        )
        self.unlock_button.clicked.connect(self._unlock)
        self.lock_button.clicked.connect(self._lock)
        self.fastboot_session.output.connect(self._on_unlock_output)
        self.fastboot_session.error.connect(self._on_unlock_error)
        self.fastboot_session.finished.connect(self._on_unlock_finished)
        self.partition_combo.currentTextChanged.connect(self._update_flash_command)
        self.image_path.textChanged.connect(self._update_flash_command)
        self.browse_button.clicked.connect(self._browse_image)
        self.copy_flash_button.clicked.connect(
            lambda: self._copy_text(self.flash_command, "镜像命令")
        )
        self.repair_button.clicked.connect(self._repair_adb)
        self.reconnect_button.clicked.connect(self._reconnect)
        self.refresh_button.clicked.connect(self._refresh_devices)
        self.version_button.clicked.connect(self._show_version)

        self._update_controls()

    def _build_reboot_group(self) -> QGroupBox:
        group = QGroupBox("重启模式")
        self.reboot_buttons: dict[str, QPushButton] = {}
        layout = QGridLayout(group)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(6)
        for index, mode in enumerate(("bootloader", "recovery", "edl", "fastboot")):
            spec = REBOOT_MODES[mode]
            button = QPushButton(spec.label)
            button.setProperty("mode", mode)
            if mode == "edl":
                button.setObjectName("Danger")
            self.reboot_buttons[mode] = button
            layout.addWidget(button, index // 2, index % 2)
        note = QLabel("EDL 仅部分机型支持；切换模式后 ADB 会断开。")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note, 2, 0, 1, 2)
        return group

    def _build_unlock_group(self) -> QGroupBox:
        group = QGroupBox("解锁与回锁")
        layout = QGridLayout(group)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(6)

        self.unlock_command = QLineEdit()
        self.unlock_command.setReadOnly(True)
        self.unlock_command.setPlaceholderText("连接设备后生成命令")
        self.copy_unlock_button = QPushButton("复制")
        self.lock_command = QLineEdit()
        self.lock_command.setReadOnly(True)
        self.lock_command.setPlaceholderText("连接设备后生成命令")
        self.copy_lock_button = QPushButton("复制")
        layout.addWidget(QLabel("解锁命令"), 0, 0)
        layout.addWidget(self.unlock_command, 0, 1)
        layout.addWidget(self.copy_unlock_button, 0, 2)
        layout.addWidget(QLabel("回锁命令"), 1, 0)
        layout.addWidget(self.lock_command, 1, 1)
        layout.addWidget(self.copy_lock_button, 1, 2)

        self.unlock_button = QPushButton("执行解锁")
        self.unlock_button.setObjectName("Danger")
        self.lock_button = QPushButton("执行回锁")
        self.lock_button.setObjectName("Danger")
        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(18)
        button_row.addWidget(self.unlock_button)
        button_row.addWidget(self.lock_button)
        button_row.addStretch(1)
        layout.addLayout(button_row, 2, 0, 1, 3)

        note = QLabel(
            "仅部分机型支持 OEM 解锁；解锁会清除数据，回锁前请确认设备状态。"
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note, 3, 0, 1, 3)
        layout.setColumnStretch(1, 1)
        return group

    def _build_image_group(self) -> QGroupBox:
        group = QGroupBox("镜像刷入命令")
        layout = QGridLayout(group)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(6)

        self.partition_combo = QComboBox()
        self.partition_combo.setEditable(True)
        self.partition_combo.addItems(PARTITIONS)
        self.partition_combo.setToolTip("可直接输入其他分区名")
        self.image_path = QLineEdit()
        self.image_path.setPlaceholderText("选择 .img 镜像文件")
        self.browse_button = QPushButton("浏览")
        layout.addWidget(QLabel("分区"), 0, 0)
        layout.addWidget(self.partition_combo, 0, 1)
        layout.addWidget(self.image_path, 0, 2)
        layout.addWidget(self.browse_button, 0, 3)

        self.flash_command = QLineEdit()
        self.flash_command.setReadOnly(True)
        self.flash_command.setPlaceholderText("生成后显示 fastboot 命令")
        self.copy_flash_button = QPushButton("复制命令")
        layout.addWidget(QLabel("命令"), 1, 0)
        layout.addWidget(self.flash_command, 1, 1, 1, 2)
        layout.addWidget(self.copy_flash_button, 1, 3)

        note = QLabel("刷入错误的镜像或分区可能导致设备无法启动。")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note, 2, 0, 1, 4)
        layout.setColumnStretch(2, 1)
        return group

    def _build_repair_group(self) -> QGroupBox:
        group = QGroupBox("ADB 修复")
        layout = QGridLayout(group)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(6)

        self.repair_button = QPushButton("重启 ADB 服务")
        self.reconnect_button = QPushButton("重连离线设备")
        self.refresh_button = QPushButton("刷新设备列表")
        self.version_button = QPushButton("查看 adb version")
        layout.addWidget(self.repair_button, 0, 0)
        layout.addWidget(self.reconnect_button, 0, 1)
        layout.addWidget(self.refresh_button, 1, 0)
        layout.addWidget(self.version_button, 1, 1)

        self.repair_output = QLabel("尚未执行 ADB 修复操作。")
        self.repair_output.setObjectName("Muted")
        self.repair_output.setWordWrap(True)
        self.repair_output.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.repair_output, 2, 0, 1, 2)
        note = QLabel("不会修改设备数据。")
        note.setObjectName("Muted")
        layout.addWidget(note, 3, 0, 1, 2)
        return group

    def on_activated(self) -> None:
        self._update_unlock_commands()
        self._update_controls()

    def on_device_changed(self, device: DeviceInfo | None) -> None:
        is_fastboot = device is not None and device.state == "fastboot"
        available = device is not None and (device.connected or is_fastboot)
        serial = device.serial if available else ""
        if serial == self._serial and is_fastboot == self._fastboot:
            return
        self._serial = serial
        self._fastboot = is_fastboot
        if serial:
            suffix = "（Fastboot）" if is_fastboot else ""
            self.device_label.setText(f"当前设备：{serial}{suffix}")
        else:
            self.device_label.setText("当前设备：未选择")
        self._update_unlock_commands()
        self._update_controls()

    def shutdown(self) -> None:
        self._closing = True
        if self._repair_job is not None:
            job = self._repair_job
            self._repair_job = None
            job.cancel()
        process = self._process
        if process is not None:
            self._process = None
            if getattr(process, "is_running", False):
                process.cancel()
        self.fastboot_session.stop()

    def _update_unlock_commands(self) -> None:
        if not self._serial or not self._fastboot:
            self.unlock_command.clear()
            self.lock_command.clear()
            self.unlock_command.setPlaceholderText("连接 fastboot 设备后生成命令")
            self.lock_command.setPlaceholderText("连接 fastboot 设备后生成命令")
            return
        try:
            self.unlock_command.setText(self.service.unlock_command(self._serial))
            self.lock_command.setText(self.service.lock_command(self._serial))
        except ValueError as exc:
            self.message_label.setText(str(exc))
            self.unlock_command.clear()
            self.lock_command.clear()

    def _reboot(self, mode: str | None) -> None:
        if not self._serial:
            self.context.status.error("请先连接设备")
            return
        if mode not in REBOOT_MODES:
            return
        spec = REBOOT_MODES[mode]
        try:
            command = self.service.reboot_command(self._serial, mode)
        except ValueError as exc:
            self.message_label.setText(str(exc))
            return
        danger = get_danger(
            spec.danger_key,
            command=command,
            detail=spec.note or None,
        )
        if not confirm_danger(self, danger):
            return
        process = self.service.reboot(self._serial, mode)
        self._track(
            process,
            f"已发送：{spec.label}",
            reboot=True,
            progress_text=f"正在发送重启命令：{spec.label}…",
        )

    def _unlock(self) -> None:
        self._run_unlock(lock=False)

    def _lock(self) -> None:
        self._run_unlock(lock=True)

    def _run_unlock(self, lock: bool) -> None:
        if not self._serial or not self._fastboot:
            self.context.status.error("请先让设备进入 fastboot 模式")
            return
        if self.fastboot_session.running:
            self.context.status.info("上一条 fastboot 命令仍在执行")
            return
        command = (
            self.service.lock_command(self._serial)
            if lock
            else self.service.unlock_command(self._serial)
        )
        danger = get_danger(
            "flash.lock" if lock else "flash.unlock",
            command=command,
            detail=(
                "回锁可能导致设备无法启动或数据丢失，请确认镜像与设备状态。"
                if lock
                else "解锁可能清除设备数据并使设备失去保修，请确认机型支持 OEM 解锁。"
            ),
        )
        if not confirm_danger(self, danger):
            return
        self._unlock_output = ""
        self.message_label.setText(
            "正在执行回锁命令…" if lock else "正在执行解锁命令…"
        )
        self.context.status.info(
            f"正在通过 fastboot 执行{'回锁' if lock else '解锁'}"
        )
        self.fastboot_session.start(
            self._serial, "oem lock" if lock else "oem unlock"
        )
        self._update_controls()

    def _on_unlock_output(self, text: str) -> None:
        if not text:
            return
        self._unlock_output = (self._unlock_output + text)[-2000:]
        self.repair_output.setText(self._unlock_output.strip())

    def _on_unlock_error(self, message: str) -> None:
        self.message_label.setText(f"解锁命令失败：{message}")
        self.context.status.error(f"Fastboot：{message}")
        self._update_controls()

    def _on_unlock_finished(self, process) -> None:
        try:
            code = process.exitCode()
        except RuntimeError:
            code = -1
        if code == 0:
            self.message_label.setText("fastboot 解锁/回锁命令已完成")
            self.context.status.success("解锁/回锁命令已完成")
        else:
            detail = self._unlock_output.strip() or f"退出码 {code}"
            self.message_label.setText(f"解锁/回锁命令失败：{detail}")
            self.context.status.error(f"解锁/回锁命令失败：{detail}")
        self._update_controls()
        QTimer.singleShot(2500, self.context.device_service.refresh)

    def _browse_image(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "选择镜像文件",
            "",
            "镜像文件 (*.img *.bin);;所有文件 (*.*)",
        )
        if path:
            self.image_path.setText(path)

    def _update_flash_command(self) -> None:
        partition = self.partition_combo.currentText().strip()
        path = self.image_path.text().strip()
        if not path:
            self.flash_command.clear()
            self.flash_command.setPlaceholderText("生成后显示 fastboot 命令")
            self._update_controls()
            return
        try:
            command = self.service.fastboot_flash_command(partition, path)
        except ValueError as exc:
            self.flash_command.clear()
            self.flash_command.setPlaceholderText(str(exc))
        else:
            self.flash_command.setText(command)
        self._update_controls()

    def _copy_text(self, edit: QLineEdit, label: str) -> None:
        text = edit.text().strip()
        if not text:
            self.context.status.error(f"没有可复制的{label}")
            return
        QApplication.clipboard().setText(text)
        self.context.status.success(f"{label}已复制")

    def _track(
        self,
        process,
        success_text: str,
        *,
        reboot: bool = False,
        progress_text: str = "",
    ) -> None:
        self._process = process
        self.message_label.setText(progress_text or f"正在执行：{success_text}…")
        process.finished.connect(
            lambda result: self._on_action_finished(
                result, success_text, reboot=reboot
            )
        )
        self._update_controls()

    def _on_action_finished(self, result, success_text: str, *, reboot: bool) -> None:
        self._process = None
        output = (getattr(result, "stdout", "") or getattr(result, "stderr", "")).strip()
        if getattr(result, "cancelled", False):
            self.message_label.setText("操作已取消")
            self.context.status.info("操作已取消")
        elif not getattr(result, "ok", False):
            detail = output or "未知错误"
            self.message_label.setText(f"{success_text}失败：{detail}")
            self.context.status.error(f"{success_text}失败：{detail}")
        else:
            self.message_label.setText(
                f"{success_text}" + (f"：{output}" if output else "")
            )
            self.context.status.success(success_text)
            if reboot:
                self.context.scrcpy.stop()
                self.context.metrics.set_device(
                    None, self.context.config.metrics_interval_ms
                )
                QTimer.singleShot(2500, self.context.device_service.refresh)
        self._update_controls()

    def _repair_adb(self) -> None:
        if self._repair_job is not None:
            return
        job = self.service.repair_adb()
        job.setParent(self)
        self._repair_job = job
        job.finished.connect(self._on_repair_finished)
        self.message_label.setText("正在重启 ADB 服务…")
        self.repair_output.setText("正在执行 kill-server / start-server…")
        job.start()
        self._update_controls()

    def _on_repair_finished(self, result) -> None:
        if self.sender() is not self._repair_job:
            return
        self._repair_job = None
        output = (getattr(result, "stdout", "") or getattr(result, "stderr", "")).strip()
        if getattr(result, "ok", False):
            self.message_label.setText("ADB 服务已重启")
            self.repair_output.setText(output or "ADB 服务已重启。")
            self.context.status.success("ADB 服务已重启")
            QTimer.singleShot(500, self.context.device_service.refresh)
        else:
            self.message_label.setText(f"重启 ADB 服务失败：{output or '未知错误'}")
            self.repair_output.setText(output or "重启 ADB 服务失败。")
            self.context.status.error("重启 ADB 服务失败")
        self._update_controls()

    def _reconnect(self) -> None:
        process = self.service.reconnect_offline()
        self.repair_output.setText("正在请求重连离线设备…")
        self._track(
            process,
            "已请求重连离线设备",
            progress_text="正在请求重连离线设备…",
        )
        QTimer.singleShot(1200, self.context.device_service.refresh)

    def _refresh_devices(self) -> None:
        self.repair_output.setText("正在刷新设备列表…")
        self.context.device_service.refresh()

    def _show_version(self) -> None:
        if self._process is not None:
            return
        process = self.service.version()
        self._process = process
        self.message_label.setText("正在读取 adb version…")
        process.finished.connect(self._on_version_finished)
        self._update_controls()

    def _on_version_finished(self, result) -> None:
        self._process = None
        output = (getattr(result, "stdout", "") or getattr(result, "stderr", "")).strip()
        if getattr(result, "ok", False):
            self.repair_output.setText(output)
            self.context.status.success("已读取 ADB 版本")
            show_text(self, "ADB 版本", output)
        else:
            self.repair_output.setText(output or "读取 ADB 版本失败。")
            self.context.status.error("读取 ADB 版本失败")
        self._update_controls()

    def _update_controls(self) -> None:
        adb_ready = bool(self._serial) and not self._fastboot
        fastboot_ready = bool(self._serial) and self._fastboot
        busy = (
            self._process is not None
            or self._repair_job is not None
            or self.fastboot_session.running
        )
        for button in self.reboot_buttons.values():
            button.setEnabled(adb_ready and not busy)
        for button in (self.unlock_button, self.lock_button):
            button.setEnabled(fastboot_ready and not busy)
        for button in (self.copy_unlock_button, self.copy_lock_button):
            button.setEnabled(fastboot_ready and not busy)
        for button in self.repair_buttons:
            button.setEnabled(not busy)
        self.copy_flash_button.setEnabled(bool(self.flash_command.text()) and not busy)
        self.browse_button.setEnabled(not busy)
