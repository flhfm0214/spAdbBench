from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from ...services.packages import PackageService, parse_foreground


class ForegroundAppBar(QWidget):
    def __init__(
        self,
        context,
        service: PackageService | None = None,
        show_refresh: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.context = context
        self.service = service or PackageService(context.adb)
        self._serial = ""
        self._package = ""
        self._activity = ""
        self._foreground_process = None
        self._restart_process = None
        self._foreground_serials: dict[object, str] = {}
        self._restart_targets: dict[object, tuple[str, str]] = {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.label = QLabel("前台应用：—")
        self.label.setObjectName("Muted")
        self.refresh_button = QPushButton("刷新前台")
        self.restart_button = QPushButton("重启前台应用")
        self.restart_button.setEnabled(False)
        layout.addWidget(self.label, 1)
        layout.addWidget(self.refresh_button)
        layout.addWidget(self.restart_button)
        self.refresh_button.setVisible(show_refresh)

        self.refresh_button.clicked.connect(self.refresh)
        self.restart_button.clicked.connect(self.restart)

    @property
    def package(self) -> str:
        return self._package

    @property
    def activity(self) -> str:
        return self._activity

    def set_serial(self, serial: str | None) -> None:
        target = serial or ""
        if target == self._serial:
            return
        self._serial = target
        self._reset()

    def _reset(self) -> None:
        self._package = ""
        self._activity = ""
        self.label.setText("前台应用：—")
        self.label.setToolTip("")
        self.restart_button.setEnabled(False)

    def refresh(self) -> None:
        if not self._serial:
            self._reset()
            return
        if self._foreground_process is not None and self._foreground_process.is_running:
            return
        self.label.setText("前台应用：读取中…")
        self.label.setToolTip("")
        process = self.service.foreground(self._serial)
        self._foreground_process = process
        self._foreground_serials[process] = self._serial
        process.finished.connect(self._on_foreground_result)

    def _on_foreground_result(self, result) -> None:
        process = self.sender()
        serial = self._foreground_serials.pop(process, self._serial)
        if serial != self._serial:
            return
        if result.cancelled:
            return
        if not result.ok:
            self._reset()
            self.label.setText("前台应用：不可读")
            return
        package, activity = parse_foreground(result.stdout)
        self._package = package
        self._activity = activity
        if package:
            text = f"前台应用：{package} / {activity}"
            self.label.setText(text)
            self.label.setToolTip(text)
        else:
            self.label.setText("前台应用：未识别")
            self.label.setToolTip("")
        self.restart_button.setEnabled(bool(package))

    def restart(self) -> None:
        if not self._serial:
            self.context.status.error("请先连接设备")
            return
        if not self._package:
            self.context.status.error("尚未识别前台应用")
            return
        if self._restart_process is not None and self._restart_process.is_running:
            return
        package = self._package
        self.restart_button.setEnabled(False)
        self.label.setText(f"前台应用：正在重启 {package}…")
        self.context.status.info(f"正在重启前台应用：{package}")
        process = self.service.restart(self._serial, package)
        self._restart_process = process
        self._restart_targets[process] = (self._serial, package)
        process.finished.connect(self._on_restart_result)

    def _on_restart_result(self, result) -> None:
        process = self.sender()
        serial, package = self._restart_targets.pop(
            process, (self._serial, self._package)
        )
        if serial != self._serial:
            return
        if result.cancelled:
            return
        output = (result.stderr or result.stdout).strip()
        if result.ok:
            self.context.status.success(f"前台应用已重启：{package}")
        else:
            self.context.status.error(f"重启前台应用失败：{output or '无输出'}")
        self.refresh()

    def cancel_queries(self) -> None:
        if self._foreground_process is not None and self._foreground_process.is_running:
            self._foreground_process.cancel()

    def shutdown(self) -> None:
        self.cancel_queries()
        if self._restart_process is not None and self._restart_process.is_running:
            self._restart_process.cancel()
