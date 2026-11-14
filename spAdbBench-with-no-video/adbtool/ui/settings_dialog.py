from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..features import ENABLE_VIDEO
from ..infrastructure.adb_locator import AdbNotFoundError, resolve_adb
from ..infrastructure.config import AppConfig
from ..infrastructure.shell_open import open_folder
from ..infrastructure.paths import resource_root
from ..infrastructure.resource_paths import portable_path
from ..services.completion_config import ensure_completion_dir


MAX_SIZE_OPTIONS = (
    ("720", 720),
    ("1080", 1080),
    ("1440", 1440),
    ("2160", 2160),
)

BITRATE_OPTIONS = (
    ("2 Mbps", 2_000_000),
    ("4 Mbps", 4_000_000),
    ("8 Mbps", 8_000_000),
    ("16 Mbps", 16_000_000),
    ("32 Mbps", 32_000_000),
)


class SettingsDialog(QDialog):
    """Application preferences, separate from the device settings page."""

    def __init__(self, context, parent=None) -> None:
        super().__init__(parent)
        self.context = context
        self._original = context.config
        self.setWindowTitle("设置")
        self.setMinimumWidth(740)
        self.resize(760, 680)
        self.setModal(True)
        self._build_ui()
        self._load(context.config)

    @staticmethod
    def _form_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("FormLabel")
        return label

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(16)

        heading = QLabel("应用设置")
        heading.setObjectName("SectionTitle")
        subtitle = QLabel(
            "界面、预览、路径与高级选项。"
            if ENABLE_VIDEO
            else "界面、路径与高级选项（无视频版本）。"
        )
        subtitle.setObjectName("Muted")
        subtitle.setWordWrap(True)
        self.summary_label = QLabel("")
        self.summary_label.setObjectName("Muted")
        self.summary_label.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(subtitle)
        layout.addWidget(self.summary_label)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_general_tab(), "常规")
        preview_index = self.tabs.addTab(self._build_preview_tab(), "屏幕预览")
        if not ENABLE_VIDEO:
            self.tabs.setTabVisible(preview_index, False)
        self.tabs.addTab(self._build_storage_tab(), "路径与资源")
        layout.addWidget(self.tabs, 1)

        self.auto_refresh_check.toggled.connect(self._update_summary)
        self.auto_refresh_check.toggled.connect(self.device_poll_spin.setEnabled)
        self.device_poll_spin.valueChanged.connect(self._update_summary)
        self.metrics_spin.valueChanged.connect(self._update_summary)
        self.theme_combo.currentIndexChanged.connect(self._update_summary)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.reset_button = QPushButton("恢复默认")
        self.reset_button.clicked.connect(self._restore_defaults)
        footer.addWidget(self.reset_button)
        footer.addStretch(1)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("Primary")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        footer.addWidget(self.buttons)
        layout.addLayout(footer)

    def _build_general_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 18, 16, 12)
        layout.setSpacing(18)

        appearance = QGroupBox("外观")
        form = QFormLayout(appearance)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setVerticalSpacing(14)
        form.setHorizontalSpacing(18)
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("跟随系统", "system")
        self.theme_combo.addItem("浅色", "light")
        self.theme_combo.addItem("深色", "dark")
        form.addRow(self._form_label("主题"), self.theme_combo)
        layout.addWidget(appearance)

        startup = QGroupBox("设备检测与采样")
        startup_hint = QLabel(
            "自动检测 ADB / Fastboot 设备；检测间隔决定设备列表刷新频率，"
            "性能采样决定 CPU、内存等面板刷新频率。"
        )
        startup_hint.setObjectName("Muted")
        startup_hint.setWordWrap(True)
        startup_layout = QVBoxLayout(startup)
        startup_layout.addWidget(startup_hint)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setVerticalSpacing(14)
        form.setHorizontalSpacing(18)
        self.auto_refresh_check = QCheckBox("自动检测 ADB / Fastboot 设备")
        self.auto_refresh_check.setToolTip("开启后按检测间隔刷新 ADB 与 Fastboot 设备")

        self.device_poll_spin = QDoubleSpinBox()
        self.device_poll_spin.setDecimals(1)
        self.device_poll_spin.setRange(0.2, 60.0)
        self.device_poll_spin.setSingleStep(0.1)
        self.device_poll_spin.setToolTip("ADB / Fastboot 检测间隔，范围 0.2–60 秒")

        self.metrics_spin = QDoubleSpinBox()
        self.metrics_spin.setDecimals(1)
        self.metrics_spin.setRange(0.0, 60.0)
        self.metrics_spin.setSingleStep(0.1)
        self.metrics_spin.setSpecialValueText("关闭")
        self.metrics_spin.setToolTip("性能采样间隔，范围 0.1–60 秒；0 表示关闭")

        form.addRow(self._form_label("自动检测"), self.auto_refresh_check)
        form.addRow(
            self._form_label("检测间隔"),
            self._unit_row(self.device_poll_spin, "秒（0.2–60）"),
        )
        form.addRow(
            self._form_label("性能采样"),
            self._unit_row(self.metrics_spin, "秒（0.1–60；0 关闭）"),
        )
        startup_layout.addLayout(form)
        layout.addWidget(startup)

        safety = QGroupBox("安全")
        safety_layout = QVBoxLayout(safety)
        note = QLabel("高风险操作会先显示确认对话框。")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        safety_layout.addWidget(note)
        layout.addWidget(safety)
        layout.addStretch(1)
        return page

    def _update_summary(self) -> None:
        if not hasattr(self, "summary_label"):
            return
        auto = "开启" if self.auto_refresh_check.isChecked() else "关闭"
        device = self.device_poll_spin.value()
        metrics = self.metrics_spin.value()
        metrics_text = "关闭" if metrics <= 0 else f"{metrics:.1f} 秒"
        self.summary_label.setText(
            f"当前：自动检测 {auto} · 检测间隔 {device:.1f} 秒 · "
            f"性能采样 {metrics_text} · 主题 {self.theme_combo.currentText()}"
        )

    def _build_preview_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(12)

        preview = QGroupBox("屏幕预览")
        form = QFormLayout(preview)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setSpacing(8)
        self.preview_fps_spin = QSpinBox()
        self.preview_fps_spin.setRange(1, 60)
        self.preview_fps_spin.setToolTip("侧边栏预览的刷新频率，范围 1–60 帧/秒")
        form.addRow(
            "刷新频率",
            self._unit_row(self.preview_fps_spin, "帧/秒（上限 60）"),
        )

        self.max_size_combo = QComboBox()
        for label, value in MAX_SIZE_OPTIONS:
            self.max_size_combo.addItem(f"{label}p", value)
        self.max_size_combo.setToolTip("发送到设备的视频最大边长")
        form.addRow("最大分辨率", self.max_size_combo)

        self.bitrate_combo = QComboBox()
        for label, value in BITRATE_OPTIONS:
            self.bitrate_combo.addItem(label, value)
        self.bitrate_combo.setToolTip("视频码率")
        form.addRow("视频码率", self.bitrate_combo)
        layout.addWidget(preview)

        auto_close = QGroupBox("自动关闭")
        close_form = QFormLayout(auto_close)
        close_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        close_form.setSpacing(8)
        self.auto_close_check = QCheckBox("无操作时自动关闭预览")
        self.auto_close_spin = QSpinBox()
        self.auto_close_spin.setRange(10, 3600)
        self.auto_close_spin.setSingleStep(10)
        self.auto_close_spin.setToolTip("应用超过该时间未操作时关闭预览")
        self.auto_close_check.toggled.connect(self.auto_close_spin.setEnabled)
        close_form.addRow(self.auto_close_check)
        close_form.addRow(
            "空闲关闭时间",
            self._unit_row(self.auto_close_spin, "秒（10–3600）"),
        )
        layout.addWidget(auto_close)

        hint = QLabel("修改后正在运行的预览会自动重连。")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        return page

    def _build_storage_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 18, 16, 12)
        layout.setSpacing(18)

        storage = QGroupBox("默认保存位置")
        storage_layout = QVBoxLayout(storage)
        storage_layout.setSpacing(10)
        row = QHBoxLayout()
        self.save_dir_edit = QLineEdit()
        self.save_dir_edit.setPlaceholderText("例如 C:\\Users\\name\\Documents\\adb-utils")
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse_save_dir)
        open_button = QPushButton("打开")
        open_button.clicked.connect(self._open_save_dir)
        row.addWidget(self.save_dir_edit, 1)
        row.addWidget(browse)
        row.addWidget(open_button)
        storage_layout.addLayout(row)
        self.save_hint = QLabel("")
        self.save_hint.setObjectName("Muted")
        self.save_hint.setWordWrap(True)
        storage_layout.addWidget(self.save_hint)
        self.save_dir_edit.textChanged.connect(self._update_save_hint)
        layout.addWidget(storage)

        paths = QGroupBox("程序与资源")
        form = QFormLayout(paths)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setVerticalSpacing(14)
        form.setHorizontalSpacing(18)

        adb_row = QHBoxLayout()
        self.adb_edit = QLineEdit()
        self.adb_edit.setPlaceholderText("留空则自动探测 platform-tools\\adb.exe")
        adb_browse = QPushButton("浏览…")
        adb_browse.clicked.connect(self._browse_adb)
        adb_auto = QPushButton("自动检测")
        adb_auto.clicked.connect(self._detect_adb)
        adb_row.addWidget(self.adb_edit, 1)
        adb_row.addWidget(adb_browse)
        adb_row.addWidget(adb_auto)
        form.addRow(self._form_label("ADB 路径"), adb_row)

        server_row = QHBoxLayout()
        self.server_edit = QLineEdit()
        server_browse = QPushButton("浏览…")
        server_browse.clicked.connect(self._browse_server)
        server_row.addWidget(self.server_edit, 1)
        server_row.addWidget(server_browse)
        if ENABLE_VIDEO:
            form.addRow(self._form_label("scrcpy-server"), server_row)

        data_row = QHBoxLayout()
        self.data_label = QLineEdit()
        self.data_label.setReadOnly(True)
        data_open = QPushButton("打开数据目录")
        data_open.clicked.connect(self._open_data_dir)
        data_row.addWidget(self.data_label, 1)
        data_row.addWidget(data_open)
        form.addRow(self._form_label("运行数据"), data_row)
        layout.addWidget(paths)
        path_hint = QLabel("路径优先使用相对项目路径；留空时自动探测内置资源。")
        path_hint.setObjectName("Muted")
        path_hint.setWordWrap(True)
        layout.addWidget(path_hint)

        completion = QGroupBox("命令补全")
        completion_layout = QVBoxLayout(completion)
        completion_layout.setSpacing(8)
        completion_row = QHBoxLayout()
        self.completion_label = QLineEdit()
        self.completion_label.setReadOnly(True)
        completion_open = QPushButton("打开补全配置目录")
        completion_open.clicked.connect(self._open_completion_dir)
        completion_row.addWidget(self.completion_label, 1)
        completion_row.addWidget(completion_open)
        completion_layout.addLayout(completion_row)
        completion_hint = QLabel(
            "编辑目录中的 commands.json 或新增 <命令>.json；保存后回终端按 Tab 自动生效。"
        )
        completion_hint.setObjectName("Muted")
        completion_hint.setWordWrap(True)
        completion_layout.addWidget(completion_hint)
        layout.addWidget(completion)

        about = QLabel(
            f"adb-utils {__version__} · 资源目录 {resource_root()}"
        )
        about.setObjectName("Muted")
        about.setWordWrap(True)
        layout.addWidget(about)
        layout.addStretch(1)
        return page

    def _unit_row(self, widget: QWidget, unit_text: str) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        widget.setMinimumWidth(110)
        label = QLabel(unit_text)
        label.setObjectName("Muted")
        layout.addWidget(widget)
        layout.addWidget(label)
        layout.addStretch(1)
        return row

    def _load(self, config: AppConfig) -> None:
        index = self.theme_combo.findData(config.theme)
        self.theme_combo.setCurrentIndex(max(0, index))
        self.auto_refresh_check.setChecked(config.auto_refresh_devices)
        self.device_poll_spin.setValue(max(0.2, config.device_poll_ms / 1000))
        self.metrics_spin.setValue(max(0.0, config.metrics_interval_ms / 1000))

        self.preview_fps_spin.setValue(config.preview_fps)
        self.auto_close_check.setChecked(config.preview_auto_close_enabled)
        self.auto_close_spin.setValue(config.preview_auto_close_seconds)
        self.auto_close_spin.setEnabled(config.preview_auto_close_enabled)
        size_index = self.max_size_combo.findData(config.scrcpy_max_size)
        self.max_size_combo.setCurrentIndex(size_index if size_index >= 0 else 1)
        bitrate_index = self.bitrate_combo.findData(config.scrcpy_bit_rate)
        self.bitrate_combo.setCurrentIndex(bitrate_index if bitrate_index >= 0 else 2)

        self.save_dir_edit.setText(config.save_dir or str(config.save_root))
        self.adb_edit.setText(config.adb_path)
        self.server_edit.setText(config.scrcpy_server_path)
        self.data_label.setText(str(self.context.config_store.root / "data"))
        self.completion_label.setText(str(self.context.completion_config_dir))
        self.server_edit.setPlaceholderText(
            "留空自动使用 vendor/scrcpy/scrcpy-server"
        )
        self._update_save_hint()
        self._update_summary()

    def _update_save_hint(self) -> None:
        root = self.save_dir_edit.text().strip() or str(AppConfig().save_root)
        self.save_hint.setText(
            f"截图、快照、APK 导出与拉取文件都保存在 {root} 下。"
        )

    def _browse_save_dir(self) -> None:
        start = self.save_dir_edit.text().strip() or str(Path.home())
        selected = QFileDialog.getExistingDirectory(self, "选择默认保存位置", start)
        if selected:
            self.save_dir_edit.setText(selected)

    def _open_save_dir(self) -> None:
        target = self.save_dir_edit.text().strip()
        if not target:
            return
        path = Path(target).expanduser()
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, "无法创建目录", str(exc))
            return
        if not open_folder(path):
            QMessageBox.warning(self, "无法打开目录", str(path))

    def _browse_adb(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "选择 adb.exe",
            self.adb_edit.text() or str(self.context.config_store.root),
            "adb.exe (adb.exe);;可执行文件 (*.exe);;所有文件 (*)",
        )
        if path:
            self.adb_edit.setText(path)

    def _detect_adb(self) -> None:
        candidate = AppConfig(adb_path="", scrcpy_server_path="")
        try:
            found = resolve_adb(candidate, self.context.config_store.root)
        except AdbNotFoundError as exc:
            QMessageBox.warning(self, "未找到 ADB", str(exc))
            return
        self.adb_edit.setText(str(found))

    def _browse_server(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "选择 scrcpy-server",
            self.server_edit.text()
            or str(self.context.config_store.root / "vendor" / "scrcpy"),
            "scrcpy-server (scrcpy-server);;所有文件 (*)",
        )
        if path:
            self.server_edit.setText(path)

    def _open_data_dir(self) -> None:
        target = self.context.config_store.root / "data"
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, "无法创建目录", str(exc))
            return
        if not open_folder(target):
            QMessageBox.warning(self, "无法打开目录", str(target))

    def _open_completion_dir(self) -> None:
        try:
            target = ensure_completion_dir(self.context.config_store.root)
        except OSError as exc:
            QMessageBox.warning(self, "无法创建补全配置目录", str(exc))
            return
        self.completion_label.setText(str(target))
        if not open_folder(target):
            QMessageBox.warning(self, "无法打开目录", str(target))

    def _restore_defaults(self) -> None:
        defaults = AppConfig()
        self._load(defaults)
        self.data_label.setText(str(self.context.config_store.root / "data"))

    def _collect(self) -> dict:
        save_text = self.save_dir_edit.text().strip()
        if not save_text:
            raise ValueError("默认保存位置不能为空")
        save_dir = Path(save_text).expanduser()
        try:
            save_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ValueError(f"无法创建默认保存位置：{exc}") from exc

        adb_text = self.adb_edit.text().strip()
        if adb_text:
            adb = Path(adb_text).expanduser()
            if not adb.is_absolute():
                adb = self.context.config_store.root / adb
            if not adb.is_file():
                raise ValueError(f"ADB 路径不存在：{adb}")
            adb_text = portable_path(adb, self.context.config_store.root)

        changes = {
            "theme": self.theme_combo.currentData(),
            "auto_refresh_devices": self.auto_refresh_check.isChecked(),
            "metrics_interval_ms": int(round(self.metrics_spin.value() * 1000)),
            "device_poll_ms": int(round(self.device_poll_spin.value() * 1000)),
            "save_dir": str(save_dir),
            "screenshot_dir": str(save_dir / "screenshots"),
            "snapshot_dir": str(save_dir / "snapshots"),
            "adb_path": adb_text,
        }
        return changes

    def save(self) -> None:
        try:
            changes = self._collect()
        except ValueError as exc:
            QMessageBox.warning(self, "设置未保存", str(exc))
            return

        try:
            self.context.apply_config(changes)
        except OSError as exc:
            QMessageBox.critical(self, "保存失败", f"无法写入配置文件：{exc}")
            return
        self.context.status.success("设置已保存")
        self.accept()
