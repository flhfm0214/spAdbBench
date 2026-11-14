from __future__ import annotations

import posixpath
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from ...infrastructure.parsers import DeviceInfo
from ...services.danger import get_danger
from ...services.transfer import TransferService, is_system_remote_path, parse_transfer_progress
from ..page import BasePage
from ..widgets.danger_dialog import confirm_danger
from ..widgets.remote_files import RemoteFileDialog


class TransferPage(BasePage):
    def __init__(self, context) -> None:
        super().__init__(context)
        self.service = TransferService(context.adb)
        self._serial = ""
        self._split_files: list[str] = []
        self._operation_process = None
        self._operation_kind = ""
        self._operation_buffer = ""
        self._scan_destination = ""
        self._cancelled = False
        self._pull_paths: list[str] = []
        self._pull_queue: list[str] = []
        self._pull_total = 0
        self._pull_done = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(10)

        header = QHBoxLayout()
        heading = QLabel("安装与文件")
        heading.setObjectName("SectionTitle")
        self.message_label = QLabel("安装 APK、推送或拉取文件。")
        self.message_label.setObjectName("Muted")
        header.addWidget(heading)
        header.addSpacing(12)
        header.addWidget(self.message_label, 1)
        layout.addLayout(header)

        layout.addWidget(self._build_install_group())
        layout.addWidget(self._build_transfer_group())

        progress_row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setVisible(False)
        progress_row.addWidget(self.progress, 1)
        progress_row.addWidget(self.cancel_button)
        layout.addLayout(progress_row)
        layout.addStretch(1)

        self.cancel_button.clicked.connect(self._cancel_current)

    def on_device_changed(self, device: DeviceInfo | None) -> None:
        self._serial = device.serial if device and device.connected else ""
        if device is None:
            self.message_label.setText("未选择设备。")
        elif not device.connected:
            self.message_label.setText(f"设备 {device.serial} 未就绪（{device.state}）。")
        else:
            self.message_label.setText(f"当前设备：{device.display_name}（{device.serial}）")

    def _build_install_group(self) -> QGroupBox:
        group = QGroupBox("安装 APK")
        layout = QGridLayout(group)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(6)

        self.apk_path = QLineEdit()
        self.apk_path.setPlaceholderText("选择本地 .apk 文件")
        browse_apk = QPushButton("浏览 APK")
        self.install_button = QPushButton("安装 APK")
        self.install_button.setObjectName("Primary")
        self.reinstall_check = QCheckBox("覆盖安装 (-r)")
        self.reinstall_check.setChecked(True)
        self.grant_check = QCheckBox("授予运行时权限 (-g)")

        layout.addWidget(QLabel("APK 文件"), 0, 0)
        layout.addWidget(self.apk_path, 0, 1, 1, 2)
        layout.addWidget(browse_apk, 0, 3)
        layout.addWidget(self.install_button, 0, 4)
        layout.addWidget(self.reinstall_check, 1, 1)
        layout.addWidget(self.grant_check, 1, 2)

        self.split_count_label = QLabel("未选择拆分 APK")
        self.split_count_label.setObjectName("Muted")
        self.split_list = QListWidget()
        self.split_list.setMaximumHeight(76)
        self.split_list.setVisible(False)
        choose_split = QPushButton("选择拆分 APK")
        self.split_install_button = QPushButton("拆分安装")
        layout.addWidget(QLabel("拆分 APK"), 2, 0)
        layout.addWidget(self.split_count_label, 2, 1, 1, 2)
        layout.addWidget(choose_split, 2, 3)
        layout.addWidget(self.split_install_button, 2, 4)
        layout.addWidget(self.split_list, 3, 1, 1, 4)

        browse_apk.clicked.connect(self._browse_apk)
        choose_split.clicked.connect(self._browse_split)
        self.install_button.clicked.connect(self._install)
        self.split_install_button.clicked.connect(self._install_split)
        return group

    def _build_transfer_group(self) -> QGroupBox:
        group = QGroupBox("文件传输")
        layout = QGridLayout(group)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(8)

        self.push_local = QLineEdit()
        self.push_local.setPlaceholderText("本地文件")
        browse_push = QPushButton("本地文件")
        self.push_remote = QLineEdit()
        self.push_remote.setPlaceholderText("设备目录或目标路径")
        browse_push_remote = QPushButton("设备目录")
        self.push_button = QPushButton("推送文件")

        self.pull_remote = QLineEdit()
        self.pull_remote.setPlaceholderText("设备文件或目录")
        browse_pull_remote = QPushButton("设备文件")
        self.pull_local_dir = QLineEdit()
        self.pull_local_dir.setPlaceholderText("本地目标目录")
        browse_pull = QPushButton("本地目录")
        self.pull_button = QPushButton("拉取文件")

        self.shot_local = QLineEdit()
        self.shot_local.setPlaceholderText("本地截图文件")
        browse_shot = QPushButton("浏览截图")
        self.shot_remote_dir = QLineEdit("/sdcard/Pictures")
        browse_shot_remote = QPushButton("设备目录")
        self.shot_button = QPushButton("推送截图")

        layout.addWidget(QLabel("推送"), 0, 0)
        layout.addWidget(self.push_local, 0, 1)
        layout.addWidget(browse_push, 0, 2)
        layout.addWidget(self.push_remote, 0, 3)
        layout.addWidget(browse_push_remote, 0, 4)
        layout.addWidget(self.push_button, 0, 5)

        layout.addWidget(QLabel("拉取"), 1, 0)
        layout.addWidget(self.pull_remote, 1, 1)
        layout.addWidget(browse_pull_remote, 1, 2)
        layout.addWidget(self.pull_local_dir, 1, 3)
        layout.addWidget(browse_pull, 1, 4)
        layout.addWidget(self.pull_button, 1, 5)

        layout.addWidget(QLabel("截图"), 2, 0)
        layout.addWidget(self.shot_local, 2, 1)
        layout.addWidget(browse_shot, 2, 2)
        layout.addWidget(self.shot_remote_dir, 2, 3)
        layout.addWidget(browse_shot_remote, 2, 4)
        layout.addWidget(self.shot_button, 2, 5)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(3, 1)

        browse_push.clicked.connect(self._browse_push)
        browse_push_remote.clicked.connect(self._browse_push_remote)
        browse_pull_remote.clicked.connect(self._browse_pull_remote)
        browse_pull.clicked.connect(self._browse_pull_dir)
        browse_shot.clicked.connect(self._browse_screenshot)
        browse_shot_remote.clicked.connect(self._browse_screenshot_remote)
        self.pull_remote.textEdited.connect(self._clear_pull_paths)
        self.push_button.clicked.connect(self._push)
        self.pull_button.clicked.connect(self._pull)
        self.shot_button.clicked.connect(self._push_screenshot)
        return group

    def _browse_apk(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "选择 APK", "", "APK (*.apk)")
        if path:
            self.apk_path.setText(path)

    def _browse_split(self) -> None:
        paths, _filter = QFileDialog.getOpenFileNames(self, "选择拆分 APK", "", "APK (*.apk)")
        if not paths:
            return
        self._split_files = paths
        self.split_list.clear()
        self.split_list.addItems(paths)
        self.split_list.setVisible(True)
        self.split_count_label.setText(f"已选择 {len(paths)} 个 APK")

    def _browse_push(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "选择本地文件")
        if path:
            self.push_local.setText(path)

    @staticmethod
    def _picker_start(text: str, *, directory: bool = False) -> str:
        path = (text or "").strip()
        if not path.startswith("/"):
            return "/sdcard"
        if path != "/" and not path.endswith("/") and not directory:
            return posixpath.dirname(path) or "/"
        return path

    def _remote_dialog(self, mode: str, start_path: str) -> RemoteFileDialog:
        return RemoteFileDialog(
            self.context.adb,
            self._serial,
            self,
            mode=mode,
            start_path=start_path,
        )

    def _browse_push_remote(self) -> None:
        if not self._require_device():
            return
        dialog = self._remote_dialog(
            "directory",
            self._picker_start(self.push_remote.text(), directory=True),
        )
        if dialog.exec() and dialog.selected_path:
            target = dialog.selected_path.rstrip("/")
            self.push_remote.setText(f"{target}/" if target else "/")

    def _browse_pull_remote(self) -> None:
        if not self._require_device():
            return
        dialog = self._remote_dialog(
            "file",
            self._picker_start(self.pull_remote.text()),
        )
        if dialog.exec() and dialog.selected_paths:
            paths = list(dialog.selected_paths)
            self._pull_paths = paths
            if len(paths) == 1:
                self.pull_remote.setText(paths[0])
                self.pull_remote.setToolTip(paths[0])
            else:
                self.pull_remote.setText(f"{paths[0]} 等 {len(paths)} 项")
                self.pull_remote.setToolTip("\n".join(paths))
                self.context.status.info(f"已选择 {len(paths)} 个设备路径")

    def _clear_pull_paths(self) -> None:
        self._pull_paths = []
        self.pull_remote.setToolTip("")

    def _browse_screenshot_remote(self) -> None:
        if not self._require_device():
            return
        dialog = self._remote_dialog(
            "directory",
            self._picker_start(self.shot_remote_dir.text(), directory=True),
        )
        if dialog.exec() and dialog.selected_path:
            self.shot_remote_dir.setText(dialog.selected_path)

    def _browse_pull_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self,
            "选择本地目录",
            str(self.context.config.save_root / "files"),
        )
        if path:
            self.pull_local_dir.setText(path)

    def _browse_screenshot(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "选择截图",
            "",
            "图片 (*.png *.jpg *.jpeg *.webp);;所有文件 (*)",
        )
        if path:
            self.shot_local.setText(path)

    def _require_device(self) -> bool:
        if not self._serial:
            self.context.status.error("请先连接设备")
            return False
        return True

    def _install(self) -> None:
        if not self._require_device():
            return
        apk = self.apk_path.text().strip()
        if not apk:
            self.context.status.error("请选择 APK")
            return
        try:
            process = self.service.install(
                self._serial,
                apk,
                reinstall=self.reinstall_check.isChecked(),
                grant=self.grant_check.isChecked(),
            )
        except ValueError as exc:
            self.context.status.error(str(exc))
            return
        self._start(process, f"安装 {Path(apk).name}", "install", indeterminate=True)

    def _install_split(self) -> None:
        if not self._require_device():
            return
        if not self._split_files:
            self.context.status.error("请选择拆分 APK")
            return
        try:
            process = self.service.install_split(
                self._serial,
                self._split_files,
                reinstall=self.reinstall_check.isChecked(),
                grant=self.grant_check.isChecked(),
            )
        except ValueError as exc:
            self.context.status.error(str(exc))
            return
        self._start(
            process,
            f"拆分安装 {len(self._split_files)} 个 APK",
            "install_split",
            indeterminate=True,
        )

    def _push(self) -> None:
        if not self._require_device():
            return
        local = self.push_local.text().strip()
        remote = self.push_remote.text().strip()
        if not local or not remote:
            self.context.status.error("请填写本地文件和远端路径")
            return
        if is_system_remote_path(remote):
            command = f"adb -s {self._serial} push {local} {remote}"
            if not confirm_danger(self, get_danger("files.push_system", command=command)):
                return
        try:
            process = self.service.push(self._serial, local, remote)
        except ValueError as exc:
            self.context.status.error(str(exc))
            return
        self._start(process, "推送文件", "push", indeterminate=False)

    def _pull(self) -> None:
        if not self._require_device():
            return
        remote = self.pull_remote.text().strip()
        local = self.pull_local_dir.text().strip()
        if not remote or not local:
            self.context.status.error("请填写远端路径和本地目录")
            return
        paths = list(self._pull_paths) if self._pull_paths else [remote]
        self._pull_queue = paths
        self._pull_total = len(paths)
        self._pull_done = 0
        self.context.status.info(
            f"拉取 {self._pull_total} 项…"
            if self._pull_total > 1
            else "拉取文件…"
        )
        self._run_next_pull(local)

    def _run_next_pull(self, local: str) -> None:
        if not self._pull_queue:
            return
        path = self._pull_queue.pop(0)
        try:
            process = self.service.pull(self._serial, path, local)
        except ValueError as exc:
            self._pull_queue.clear()
            self.context.status.error(str(exc))
            return
        name = posixpath.basename(path.rstrip("/")) or path
        self._start(process, f"拉取 {name}", "pull", indeterminate=False)

    def _push_screenshot(self) -> None:
        if not self._require_device():
            return
        local = self.shot_local.text().strip()
        remote_dir = self.shot_remote_dir.text().strip()
        if not local or not remote_dir:
            self.context.status.error("请选择截图并填写远端目录")
            return
        try:
            destination = self.service.screenshot_destination(local, remote_dir)
        except ValueError as exc:
            self.context.status.error(str(exc))
            return
        if is_system_remote_path(destination):
            command = f"adb -s {self._serial} push {local} {destination}"
            if not confirm_danger(self, get_danger("files.push_system", command=command)):
                return
        try:
            process, destination = self.service.push_screenshot(self._serial, local, remote_dir)
        except ValueError as exc:
            self.context.status.error(str(exc))
            return
        self._scan_destination = destination
        self._start(process, "推送截图", "screenshot", indeterminate=False)

    def _start(self, process, label: str, kind: str, indeterminate: bool) -> None:
        if self._operation_process is not None and self._operation_process.is_running:
            self.context.status.error("已有文件操作正在执行")
            return
        self._operation_process = process
        self._operation_kind = kind
        self._operation_buffer = ""
        self._cancelled = False
        self.progress.setVisible(True)
        if indeterminate:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
        self.cancel_button.setVisible(True)
        self.context.status.info(f"{label}…")
        process.output.connect(self._on_output)
        process.error_output.connect(self._on_output)
        process.finished.connect(lambda result, l=label: self._on_finished(l, result))

    def _on_output(self, chunk: str) -> None:
        if not chunk:
            return
        self._operation_buffer = (self._operation_buffer + chunk)[-4000:]
        percent = parse_transfer_progress(self._operation_buffer)
        if percent is not None and self._operation_kind != "install" and self._operation_kind != "install_split":
            self.progress.setRange(0, 100)
            self.progress.setValue(percent)

    def _on_finished(self, label: str, result) -> None:
        self._operation_process = None
        self.progress.setVisible(False)
        self.cancel_button.setVisible(False)
        if self._cancelled or result.cancelled:
            self._cancelled = False
            self._pull_queue.clear()
            self._pull_total = 0
            self.context.status.info(f"{label}已取消")
            return
        if not result.ok:
            self._pull_queue.clear()
            self._pull_total = 0
            self.context.status.error(
                f"{label}失败：{(result.stderr or result.stdout).strip() or '未知错误'}"
            )
            return

        if self._operation_kind == "pull":
            self._pull_done += 1
            if self._pull_queue:
                self.context.status.success(
                    f"已拉取 {self._pull_done}/{self._pull_total} 项"
                )
                self._run_next_pull(self.pull_local_dir.text().strip())
                return
            if self._pull_total > 1:
                self.context.status.success(f"已拉取 {self._pull_total} 项")
                return

        if self._operation_kind == "screenshot" and self._scan_destination:
            destination = self._scan_destination
            self._scan_destination = ""
            scan = self.service.media_scan(self._serial, destination)
            scan.finished.connect(
                lambda scan_result: self.context.status.info(
                    "截图已推送" if scan_result.ok else "截图已推送，媒体库刷新失败"
                )
            )
        else:
            self.context.status.success(f"{label}完成")

    def _cancel_current(self) -> None:
        if self._operation_process is not None and self._operation_process.is_running:
            self._cancelled = True
            self._pull_queue.clear()
            self._pull_total = 0
            self._operation_process.cancel()
            self.context.status.info("正在取消…")
