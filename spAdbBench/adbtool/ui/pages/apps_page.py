from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ...infrastructure.parsers import DeviceInfo
from ...services.packages import (
    BatchExtractJob,
    BatchItemResult,
    BatchPackageJob,
    PackageInfo,
    PackageService,
    filter_packages,
)
from ...services.danger import get_danger
from ..page import BasePage
from ..widgets.danger_dialog import confirm_danger
from ..widgets.foreground_bar import ForegroundAppBar
from ..widgets.result_dialog import show_results, show_text


FILTERS = [
    ("全部应用", "all"),
    ("第三方应用", "third"),
    ("系统应用", "system"),
    ("已禁用", "disabled"),
]

SINGLE_ACTIONS = [
    ("enable", "启用"),
    ("disable", "禁用"),
    ("launch", "启动"),
    ("force_stop", "强行停止"),
    ("clear", "清除数据"),
    ("uninstall", "卸载"),
    ("uninstall_keep", "保留数据卸载"),
    ("restore", "恢复系统软件"),
    ("extract", "导出所选 APK"),
    ("info", "应用信息"),
]


class AppsPage(BasePage):
    def __init__(self, context) -> None:
        super().__init__(context)
        self.service = PackageService(context.adb)
        self._packages: list[PackageInfo] = []
        self._checked: set[str] = set()
        self._check_anchor_row: int | None = None
        self._serial = ""
        self._loaded_serial = ""
        self._list_process = None
        self._action_process = None
        self._batch_job = None
        self._extract_job = None
        self._extract_cancelled = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(8)

        header = QHBoxLayout()
        heading = QLabel("应用管理")
        heading.setObjectName("SectionTitle")
        self.foreground_bar = ForegroundAppBar(context, show_refresh=False)
        self.foreground_label = self.foreground_bar.label
        self.refresh_button = QPushButton("刷新应用")
        header.addWidget(heading)
        header.addSpacing(12)
        header.addWidget(self.foreground_bar, 1)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        toolbar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索包名")
        self.search.setClearButtonEnabled(True)
        self.filter_combo = QComboBox()
        for label, mode in FILTERS:
            self.filter_combo.addItem(label, mode)
        self.count_label = QLabel("0 / 0 个应用")
        self.count_label.setObjectName("Muted")
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(self.filter_combo)
        toolbar.addWidget(self.count_label)
        layout.addLayout(toolbar)

        selection_row = QHBoxLayout()
        self.checked_count_label = QLabel("已选 0 个")
        self.checked_count_label.setObjectName("Muted")
        self.select_all_button = QPushButton("全选当前结果")
        self.clear_selection_button = QPushButton("清空选择")
        selection_row.addWidget(self.checked_count_label)
        selection_row.addWidget(self.select_all_button)
        selection_row.addWidget(self.clear_selection_button)
        selection_row.addStretch(1)
        layout.addLayout(selection_row)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["选择", "包名", "类型", "状态"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.viewport().installEventFilter(self)
        layout.addWidget(self.table, 1)

        actions_row = QGridLayout()
        actions_row.setHorizontalSpacing(6)
        actions_row.setVerticalSpacing(6)
        self.action_buttons: dict[str, QPushButton] = {}
        for index, (action, label) in enumerate(SINGLE_ACTIONS):
            button = QPushButton(label)
            button.setEnabled(False)
            button.clicked.connect(lambda _checked=False, a=action: self._run_single(a))
            self.action_buttons[action] = button
            actions_row.addWidget(button, index // 3, index % 3)
        actions_row.setColumnStretch(3, 1)
        layout.addLayout(actions_row)

        batch_row = QGridLayout()
        batch_row.setHorizontalSpacing(6)
        batch_row.setVerticalSpacing(6)
        self.batch_enable_button = QPushButton("启用所选")
        self.batch_disable_button = QPushButton("禁用所选")
        self.google_disable_button = QPushButton("禁用 Google 套件")
        self.google_enable_button = QPushButton("启用 Google 套件")
        for index, button in enumerate(
            (
                self.batch_enable_button,
                self.batch_disable_button,
                self.google_disable_button,
                self.google_enable_button,
            )
        ):
            batch_row.addWidget(button, index // 2, index % 2)
        batch_row.setColumnStretch(2, 1)
        layout.addLayout(batch_row)

        progress_row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.cancel_extract_button = QPushButton("取消导出")
        self.cancel_extract_button.setVisible(False)
        self.cancel_batch_button = QPushButton("取消批量操作")
        self.cancel_batch_button.setVisible(False)
        progress_row.addWidget(self.progress, 1)
        progress_row.addWidget(self.cancel_extract_button)
        progress_row.addWidget(self.cancel_batch_button)
        layout.addLayout(progress_row)

        self.refresh_button.clicked.connect(self._refresh_all)
        self.search.textChanged.connect(self._render_packages)
        self.filter_combo.currentIndexChanged.connect(self._render_packages)
        self.table.itemSelectionChanged.connect(self._update_action_buttons)
        self.table.itemChanged.connect(self._on_item_changed)
        self.select_all_button.clicked.connect(self._select_all_visible)
        self.clear_selection_button.clicked.connect(self._clear_selection)
        self.batch_enable_button.clicked.connect(lambda: self._run_batch("enable"))
        self.batch_disable_button.clicked.connect(lambda: self._run_batch("disable"))
        self.google_disable_button.clicked.connect(lambda: self._run_google(False))
        self.google_enable_button.clicked.connect(lambda: self._run_google(True))
        self.cancel_extract_button.clicked.connect(self._cancel_extract)
        self.cancel_batch_button.clicked.connect(self._cancel_batch)

    def on_activated(self) -> None:
        device = self.context.current_device
        if device and device.connected:
            if device.serial != self._serial:
                self.on_device_changed(device)
                return
            self._refresh_packages()
            self.foreground_bar.refresh()

    def on_device_changed(self, device: DeviceInfo | None) -> None:
        serial = device.serial if device and device.connected else ""
        if serial == self._serial and (serial == "" or self._loaded_serial == serial):
            return
        self._serial = serial
        self._loaded_serial = ""
        self._packages = []
        self._checked.clear()
        self._check_anchor_row = None
        self.foreground_bar.set_serial(serial)
        self._render_packages()
        if serial:
            self._refresh_packages()
            self.foreground_bar.refresh()

    def _refresh_all(self) -> None:
        self._refresh_packages()
        self.foreground_bar.refresh()

    def _refresh_packages(self) -> None:
        if not self._serial:
            self.context.status.error("请先连接设备")
            return
        if self._list_process is not None and self._list_process.is_running:
            return
        self.refresh_button.setEnabled(False)
        self.context.status.info("正在读取应用列表…")
        self._list_process = self.service.list_packages(self._serial)
        self._list_process.finished.connect(lambda result, serial=self._serial: self._on_packages(serial, result))

    def _on_packages(self, serial: str, result) -> None:
        self.refresh_button.setEnabled(True)
        if serial != self._serial:
            return
        if result.cancelled:
            return
        if not result.ok:
            self.context.status.error((result.stderr or result.stdout).strip() or "读取应用列表失败")
            return
        from ...services.packages import parse_package_listing

        self._packages = parse_package_listing(result.stdout)
        present = {info.package for info in self._packages}
        self._checked &= present
        self._loaded_serial = serial
        self._render_packages()
        self.context.status.success(f"已读取 {len(self._packages)} 个应用")
        self.foreground_bar.refresh()

    def _render_packages(self) -> None:
        mode = self.filter_combo.currentData() or "all"
        visible = filter_packages(self._packages, self.search.text(), mode)
        self._check_anchor_row = None
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for info in visible:
            row = self.table.rowCount()
            self.table.insertRow(row)
            check = QTableWidgetItem()
            check.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            check.setCheckState(
                Qt.CheckState.Checked if info.package in self._checked else Qt.CheckState.Unchecked
            )
            self.table.setItem(row, 0, check)
            package_item = QTableWidgetItem(info.package)
            package_item.setData(Qt.ItemDataRole.UserRole, info)
            self.table.setItem(row, 1, package_item)
            self.table.setItem(row, 2, QTableWidgetItem("系统" if info.system else "第三方"))
            self.table.setItem(row, 3, QTableWidgetItem("已启用" if info.enabled else "已禁用"))
        self.table.blockSignals(False)
        self.count_label.setText(f"{len(visible)} / {len(self._packages)} 个应用")
        self._update_checked_count()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.table.viewport():
            if event.type() in (
                QEvent.Type.MouseButtonPress,
                QEvent.Type.MouseButtonDblClick,
            ) and event.button() == Qt.MouseButton.LeftButton:
                index = self.table.indexAt(event.position().toPoint())
                if index.isValid():
                    row = index.row()
                    column = index.column()
                    shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                    if event.type() == QEvent.Type.MouseButtonDblClick:
                        if column != 0:
                            self._toggle_row_check(row)
                            return True
                    elif shift and column != 0 and self._check_anchor_row is not None:
                        self._check_range(self._check_anchor_row, row)
                        return True
                    elif column == 0:
                        if shift and self._check_anchor_row is not None:
                            self._check_range(self._check_anchor_row, row)
                            return True
                        self._check_anchor_row = row
        return super().eventFilter(watched, event)

    def _toggle_row_check(self, row: int) -> None:
        item = self.table.item(row, 0)
        if item is None:
            return
        item.setCheckState(
            Qt.CheckState.Unchecked
            if item.checkState() == Qt.CheckState.Checked
            else Qt.CheckState.Checked
        )
        self._check_anchor_row = row
        self.table.setCurrentCell(row, 1)

    def _check_range(self, start: int, end: int) -> None:
        first, last = sorted((start, end))
        self.table.blockSignals(True)
        for row in range(first, last + 1):
            item = self.table.item(row, 0)
            package_item = self.table.item(row, 1)
            if item is None or package_item is None:
                continue
            item.setCheckState(Qt.CheckState.Checked)
            self._checked.add(package_item.text())
        self.table.blockSignals(False)
        self.table.setCurrentCell(end, 1)
        self._update_checked_count()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        package_item = self.table.item(item.row(), 1)
        if package_item is None:
            return
        package = package_item.text()
        if item.checkState() == Qt.CheckState.Checked:
            self._checked.add(package)
        else:
            self._checked.discard(package)
        self._check_anchor_row = item.row()
        self._update_checked_count()

    def _update_checked_count(self) -> None:
        count = len(self._checked)
        self.checked_count_label.setText(f"已选 {count} 个")
        idle = self._batch_job is None and self._extract_job is None
        selected = count > 0 and idle
        self.batch_enable_button.setEnabled(selected)
        self.batch_disable_button.setEnabled(selected)
        google_ready = bool(self._serial) and bool(self._packages) and idle
        self.google_disable_button.setEnabled(google_ready)
        self.google_enable_button.setEnabled(google_ready)
        self._update_action_buttons()

    def _select_all_visible(self) -> None:
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            package_item = self.table.item(row, 1)
            if package_item is not None:
                self._checked.add(package_item.text())
                self.table.item(row, 0).setCheckState(Qt.CheckState.Checked)
        self.table.blockSignals(False)
        self._update_checked_count()

    def _clear_selection(self) -> None:
        self._checked.clear()
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            self.table.item(row, 0).setCheckState(Qt.CheckState.Unchecked)
        self.table.blockSignals(False)
        self._update_checked_count()

    def _checked_package(self) -> str:
        if len(self._checked) != 1:
            return ""
        return next(iter(self._checked))

    def _update_action_buttons(self) -> None:
        has_device = bool(self._serial)
        count = len(self._checked)
        package = self._checked_package()
        info = None
        if package:
            info = next((p for p in self._packages if p.package == package), None)
        idle = self._batch_job is None and self._extract_job is None
        for action, button in self.action_buttons.items():
            if action == "extract":
                button.setEnabled(has_device and count > 0 and idle)
            elif not has_device or info is None:
                button.setEnabled(False)
            elif action == "restore":
                button.setEnabled(True)
            elif action == "enable":
                button.setEnabled(not info.enabled)
            elif action == "disable":
                button.setEnabled(info.enabled)
            else:
                button.setEnabled(True)

    def _run_single(self, action: str) -> None:
        if not self._serial:
            self.context.status.error("请先连接设备")
            return
        if action == "extract":
            self._export_selected()
            return
        if action == "restore":
            package, ok = QInputDialog.getText(
                self,
                "恢复系统软件",
                "包名",
                text=self._checked_package(),
            )
            package = package.strip()
            if not ok or not package:
                return
        else:
            package = self._checked_package()
            if not package:
                self.context.status.error("请先勾选一个应用")
                return

        try:
            command = f"adb -s {self._serial} shell {PackageService.action_command(action, package)}"
        except ValueError as exc:
            self.context.status.error(str(exc))
            return
        danger_keys = {
            "clear": "app.clear_data",
            "uninstall": "app.uninstall",
            "uninstall_keep": "app.uninstall_keep_data",
            "disable": "app.batch_disable",
        }
        danger_key = danger_keys.get(action)
        if danger_key and not confirm_danger(
            self,
            get_danger(
                danger_key,
                command=command,
                count=1 if danger_key == "app.batch_disable" else None,
                detail=package if danger_key == "app.batch_disable" else "",
            ),
        ):
            return

        self.context.status.info(f"正在执行：{action} {package}")
        self._action_process = self.service.action(self._serial, action, package)
        self._action_process.finished.connect(
            lambda result, a=action, p=package: self._on_action_done(a, p, result)
        )

    def _on_action_done(self, action: str, package: str, result) -> None:
        output = (result.stdout or result.stderr).strip()
        if action == "info":
            if not result.ok:
                self.context.status.error(output or "读取应用信息失败")
            show_text(self, f"{package} · 应用信息", result.stdout or result.stderr or "无输出")
            return
        if result.ok:
            self.context.status.success(f"{package}：{action} 完成")
        else:
            self.context.status.error(f"{package}：{action} 失败，{output or '无输出'}")
        if action in {"enable", "disable", "clear", "uninstall", "uninstall_keep", "restore"}:
            self._refresh_packages()

    def _export_selected(self) -> None:
        packages = sorted(self._checked)
        if not packages:
            self.context.status.error("请先勾选应用")
            return
        target = QFileDialog.getExistingDirectory(
            self,
            "选择 APK 保存目录",
            str(self.context.config.save_root / "apk"),
        )
        if not target:
            return
        self.progress.setVisible(True)
        self.progress.setRange(0, len(packages))
        self.progress.setValue(0)
        self.progress.setFormat(f"0/{len(packages)} 个应用")
        self.cancel_extract_button.setVisible(True)
        self._extract_cancelled = False
        self.context.status.info(f"正在导出 {len(packages)} 个应用的安装包…")
        job = BatchExtractJob(
            self.service,
            self._serial,
            packages,
            Path(target),
            self,
        )
        self._extract_job = job
        job.progress.connect(self._on_extract_progress)
        job.failed.connect(self._on_extract_failed)
        job.finished.connect(self._on_extract_finished)
        self._update_checked_count()
        job.start()

    def _on_extract_progress(self, current: int, total: int) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(current)
        self.progress.setFormat(f"{current}/{total} 个应用")

    def _on_extract_failed(self, message: str) -> None:
        self._extract_job = None
        self.progress.setVisible(False)
        self.cancel_extract_button.setVisible(False)
        self.context.status.error(message)
        self._update_checked_count()
        show_text(self, "APK 导出失败", message)

    def _on_extract_finished(self, items) -> None:
        self._extract_job = None
        self.progress.setVisible(False)
        self.cancel_extract_button.setVisible(False)
        self._update_checked_count()
        if self._extract_cancelled:
            self._extract_cancelled = False
            return
        if not items:
            self.context.status.info("没有提取到文件")
            return
        rows = []
        for item in items:
            label = item.package or "未知应用"
            if item.local:
                label = f"{label} · {Path(item.local).name}"
            rows.append((label, item.ok, item.output))
        show_results(self, "APK 导出结果", rows)

    def _cancel_extract(self) -> None:
        self._extract_cancelled = True
        if self._extract_job is not None:
            self._extract_job.cancel()
        self.progress.setVisible(False)
        self.cancel_extract_button.setVisible(False)
        self._update_checked_count()
        self.context.status.info("已取消 APK 导出")

    def _run_batch(self, action: str) -> None:
        if not self._serial:
            self.context.status.error("请先连接设备")
            return
        packages = sorted(self._checked)
        if not packages:
            self.context.status.error("请先勾选应用")
            return
        if action == "disable":
            detail = "\n".join(packages[:12])
            if len(packages) > 12:
                detail += f"\n…共 {len(packages)} 个"
            if not confirm_danger(
                self,
                get_danger(
                    "app.batch_disable",
                    command=f"adb -s {self._serial} shell pm disable-user --user 0 <包名>",
                    count=len(packages),
                    detail=detail,
                ),
            ):
                return
        self._start_batch(action, packages)

    def _run_google(self, enable: bool) -> None:
        if not self._serial:
            self.context.status.error("请先连接设备")
            return
        packages = self.service.google_candidates(self._packages, enable)
        if not packages:
            self.context.status.info("没有需要处理的 Google 套件")
            return
        if not enable:
            detail = "\n".join(packages[:12])
            if len(packages) > 12:
                detail += f"\n…共 {len(packages)} 个"
            if not confirm_danger(
                self,
                get_danger(
                    "app.batch_disable_google",
                    command=f"adb -s {self._serial} shell pm disable-user --user 0 <包名>",
                    count=len(packages),
                    detail=detail,
                ),
            ):
                return
        self._start_batch("enable" if enable else "disable", packages)

    def _start_batch(self, action: str, packages: list[str]) -> None:
        if self._batch_job is not None:
            self.context.status.error("已有批量操作正在执行")
            return
        self.context.status.info(f"正在批量 {action} {len(packages)} 个应用…")
        self.progress.setVisible(True)
        self.progress.setRange(0, len(packages))
        self.progress.setValue(0)
        self.cancel_batch_button.setVisible(True)
        self.batch_enable_button.setEnabled(False)
        self.batch_disable_button.setEnabled(False)
        job = BatchPackageJob(self.service, self._serial, action, packages, self)
        self._batch_job = job
        job.progress.connect(self._on_batch_progress)
        job.finished.connect(self._on_batch_finished)
        job.start()

    def _on_batch_progress(self, current: int, total: int) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(current)

    def _on_batch_finished(self, results: list[BatchItemResult]) -> None:
        self._batch_job = None
        self.progress.setVisible(False)
        self.cancel_batch_button.setVisible(False)
        self._update_checked_count()
        rows = [(result.package, result.ok, result.output) for result in results]
        show_results(self, "批量操作结果", rows)
        self._refresh_packages()

    def _cancel_batch(self) -> None:
        if self._batch_job is not None:
            self._batch_job.cancel()
        self.context.status.info("已请求取消批量操作")

    def on_deactivated(self) -> None:
        if self._list_process is not None and self._list_process.is_running:
            self._list_process.cancel()
        self.foreground_bar.cancel_queries()

    def shutdown(self) -> None:
        if self._list_process is not None and self._list_process.is_running:
            self._list_process.cancel()
        self.foreground_bar.shutdown()
