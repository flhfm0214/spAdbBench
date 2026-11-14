from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QDesktopServices,
    QKeySequence,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..infrastructure.parsers import DeviceInfo, parse_wm_size
from ..infrastructure.theme import apply_theme
from ..services.fastboot import FastbootDevice, FastbootService
from .context import AppContext
from .control_window import ControlWindow
from .page import BasePage
from .pages.apps_page import AppsPage
from .pages.battery_page import BatteryPage
from .pages.device_page import DevicePage
from .pages.display_page import DisplayPage
from .pages.flash_page import FlashPage
from .pages.log_page import LogPage
from .pages.logcat_page import LogcatPage
from .pages.performance_page import PerformancePage
from .pages.script_page import ScriptPage
from .pages.settings_page import SettingsPage
from .pages.snapshot_page import SnapshotPage
from .pages.terminal_page import TerminalPage
from .pages.transfer_page import TransferPage
from .settings_dialog import SettingsDialog
from .widgets.github_icon import github_mark_icon
from .widgets.metrics_panel import MetricsPanel
from .widgets.selectable import install_selectable_labels
from .widgets.toast import ToastBanner
from .widgets.video_panel import VideoPanel


NAV_ITEMS = [
    ("设备与连接", "管理设备、无线调试与重启。"),
    ("应用管理", "应用列表、启停、卸载、APK 提取与 Google 套件。"),
    ("安装与文件", "安装 APK、推送与拉取文件。"),
    ("屏幕与按键", "分辨率、DPI、按键与截图。"),
    ("性能监控", "CPU、内存、电池与 GPU 渲染器。"),
    ("Logcat", "实时日志与过滤。"),
    ("系统设置", "字体、动画、锁屏、沉浸模式与隐藏设置。"),
    ("电池与电源", "电池信息、模拟状态与采样导出。"),
    ("刷机辅助", "Fastboot/Recovery/EDL 入口与 ADB 修复。"),
    ("脚本", "执行 .bat 子集并逐行回显。"),
    ("终端", "长驻 adb shell 与 Tab 补全。"),
    ("配置快照", "导出、对比与回滚设备配置。"),
    ("运行日志", "记录每次 ADB 命令、输出与耗时。"),
]

PROJECT_URL = "https://github.com/flhfm0214/spAdbBench"

STATE_TEXT = {
    "device": "已连接",
    "offline": "离线",
    "unauthorized": "未授权",
    "no permissions": "无权限",
    "fastboot": "Fastboot",
}

PREVIEW_ACTIVE_STATES = {"启动服务", "等待控制连接", "等待视频", "已连接"}

PREVIEW_ACTIVITY_EVENTS = {
    QEvent.Type.MouseButtonPress,
    QEvent.Type.MouseButtonDblClick,
    QEvent.Type.KeyPress,
    QEvent.Type.Wheel,
    QEvent.Type.TouchBegin,
}


class MainWindow(QMainWindow):
    def __init__(self, context: AppContext, auto_refresh: bool = True) -> None:
        super().__init__()
        self.context = context
        install_selectable_labels(QApplication.instance())
        self.control_windows: dict[str, ControlWindow] = {}
        self._quiet_refresh = False
        self._allow_polling = bool(auto_refresh)
        self._known_serials: set[str] | None = None
        self._known_fastboot: set[str] | None = None
        self._fastboot_devices: list[FastbootDevice] = []
        self._devices_signature: tuple | None = None
        self.setWindowTitle("spAdbBench · ADB 桌面工具箱")
        self.resize(1240, 780)
        self.setMinimumSize(980, 640)

        self._build_menus()
        self._build_central()
        self._build_dock()
        self._preview_enabled = True
        self.video_panel.set_preview_enabled(True)
        self._preview_idle_timer = QTimer(self)
        self._preview_idle_timer.setSingleShot(True)
        self._preview_idle_timer.timeout.connect(self._auto_close_preview)
        self._build_status_bar()
        self._connect_context()
        self._apply_initial_theme()
        self._select_device(None)

        self.toast = ToastBanner(self.centralWidget())
        self.toast.hide()
        self.fastboot_service = FastbootService(context.adb, self)
        self.fastboot_service.devices_changed.connect(self._on_fastboot_devices)
        self.fastboot_service.failed.connect(self._on_fastboot_failed)
        self.device_poll_timer = QTimer(self)
        self.device_poll_timer.setInterval(
            max(200, int(context.config.device_poll_ms))
        )
        self.device_poll_timer.timeout.connect(self._poll_devices)
        if self._allow_polling and context.config.auto_refresh_devices:
            self.device_poll_timer.start()

        self._resume_poll_after_probe = False
        self.startup_probe_timer = QTimer(self)
        self.startup_probe_timer.setInterval(
            max(200, int(context.config.device_poll_ms))
        )
        self.startup_probe_timer.timeout.connect(self._probe_for_devices)
        if auto_refresh:
            QTimer.singleShot(0, self._start_startup_probe)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def _build_menus(self) -> None:
        view_menu = self.menuBar().addMenu("视图")

        theme_menu = view_menu.addMenu("主题")
        self.theme_group = QActionGroup(self)
        self.theme_group.setExclusive(True)
        self.theme_actions: dict[str, QAction] = {}
        for mode, label in (("light", "浅色"), ("dark", "深色"), ("system", "跟随系统")):
            action = QAction(label, self, checkable=True)
            action.setData(mode)
            action.triggered.connect(lambda _checked=False, m=mode: self.set_theme(m))
            self.theme_group.addAction(action)
            theme_menu.addAction(action)
            self.theme_actions[mode] = action

        view_menu.addSeparator()
        settings_action = QAction("设置…", self)
        settings_action.setShortcut(QKeySequence("Ctrl+,"))
        settings_action.triggered.connect(self.open_settings)
        view_menu.addAction(settings_action)

    def _build_central(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        top_bar = QWidget()
        top_bar.setObjectName("TopBar")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(18, 10, 18, 10)
        top_layout.setSpacing(10)

        device_label = QLabel("当前设备")
        device_label.setObjectName("Muted")
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(320)
        self.device_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.refresh_button = QPushButton("刷新设备")
        self.connection_label = QLabel("未连接")
        self.connection_label.setObjectName("Muted")

        top_layout.addWidget(device_label)
        top_layout.addWidget(self.device_combo)
        top_layout.addWidget(self.refresh_button)
        top_layout.addSpacing(12)
        top_layout.addWidget(self.connection_label)
        top_layout.addStretch(1)
        root.addWidget(top_bar)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(180)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 8)
        sidebar_layout.setSpacing(0)

        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        self.stack = QStackedWidget()
        self.pages: list[BasePage] = [
            DevicePage(self.context),
            AppsPage(self.context),
            TransferPage(self.context),
            DisplayPage(self.context),
            PerformancePage(self.context),
            LogcatPage(self.context),
            SettingsPage(self.context),
            BatteryPage(self.context),
            FlashPage(self.context),
            ScriptPage(self.context),
            TerminalPage(self.context),
            SnapshotPage(self.context),
            LogPage(self.context),
        ]
        for title, _description in NAV_ITEMS:
            self.nav.addItem(title)
        for page in self.pages:
            self.stack.addWidget(page)

        self.settings_button = QPushButton("设置")
        self.settings_button.setObjectName("NavSettings")
        self.settings_button.setToolTip("应用设置（Ctrl+,）")
        self.settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_button.clicked.connect(self.open_settings)
        self.project_box = QWidget()
        self.project_box.setObjectName("ProjectLinkBox")
        self.project_box.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground, True
        )
        project_layout = QHBoxLayout(self.project_box)
        project_layout.setContentsMargins(16, 4, 8, 8)
        project_layout.setSpacing(6)
        self.project_icon = QPushButton()
        self.project_icon.setObjectName("ProjectLinkIcon")
        self.project_icon.setIcon(github_mark_icon(18))
        self.project_icon.setIconSize(QSize(18, 18))
        self.project_icon.setFixedSize(22, 22)
        self.project_icon.setFlat(True)
        self.project_icon.setToolTip(PROJECT_URL)
        self.project_icon.setCursor(Qt.CursorShape.PointingHandCursor)
        self.project_icon.clicked.connect(self._open_project_page)
        self.project_link = QLabel(
            f'<a href="{PROJECT_URL}" style="text-decoration:none;">'
            '<span style="font-size:12px; color:#ffffff;">github项目地址:</span><br>'
            '<span style="font-size:13px; font-weight:600; '
            'text-decoration:underline;">spAdbBench</span>'
            "</a>"
        )
        self.project_link.setObjectName("ProjectLink")
        self.project_link.setTextFormat(Qt.TextFormat.RichText)
        self.project_link.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
        )
        self.project_link.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.project_link.setToolTip(PROJECT_URL)
        self.project_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self.project_link.linkActivated.connect(
            lambda _url: self._open_project_page()
        )
        project_layout.addWidget(
            self.project_icon, 0, Qt.AlignmentFlag.AlignVCenter
        )
        project_layout.addWidget(self.project_link, 1)
        sidebar_layout.addWidget(self.nav, 1)
        sidebar_layout.addWidget(self.settings_button)
        sidebar_layout.addSpacing(10)
        sidebar_layout.addWidget(self.project_box)

        body_layout.addWidget(sidebar)
        body_layout.addWidget(self.stack, 1)
        root.addWidget(body, 1)
        self.setCentralWidget(central)

        self.nav.currentRowChanged.connect(self._on_nav_changed)
        self.refresh_button.clicked.connect(self.refresh_devices)
        self.device_combo.currentIndexChanged.connect(self._on_combo_changed)
        self.nav.setCurrentRow(0)

    def _build_dock(self) -> None:
        self.device_dock = QDockWidget("屏幕预览", self)
        self.device_dock.setObjectName("DeviceDock")
        self.device_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.device_dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.video_panel = VideoPanel(self.context.scrcpy, preview_only=True)
        self.video_panel.setMinimumHeight(260)

        info_heading = QLabel("实时信息")
        info_heading.setObjectName("SectionTitle")
        self.metrics_panel = MetricsPanel(self.context)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.video_panel)
        info = QWidget()
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(2, 8, 2, 2)
        info_layout.setSpacing(6)
        info_layout.addWidget(info_heading)
        info_layout.addWidget(self.metrics_panel, 1)
        splitter.addWidget(info)
        splitter.setSizes([300, 230])
        layout.addWidget(splitter, 1)

        self.device_dock.setWidget(panel)
        self.device_dock.setFixedWidth(340)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.device_dock)

    def _build_status_bar(self) -> None:
        self.status_summary = QLabel("未连接设备")
        self.status_message = QLabel("就绪")
        self.status_message.setObjectName("Muted")
        for label in (self.status_summary, self.status_message):
            label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            label.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.statusBar().addWidget(self.status_summary)
        self.statusBar().addPermanentWidget(self.status_message, 1)

    def _connect_context(self) -> None:
        self.context.status.message.connect(self._on_status_message)
        self.context.config_changed.connect(self._on_config_changed)
        self.context.device_service.devices_changed.connect(self._on_devices_changed)
        self.context.device_service.refresh_failed.connect(self._on_refresh_failed)
        self.context.device_service.refresh_started.connect(self._on_refresh_started)
        self.context.device_selected.connect(self._select_device)
        self.context.device_visibility_changed.connect(
            self._on_device_visibility_changed
        )
        self.context.metrics.sample_failed.connect(self._on_metrics_failed)
        self.context.scrcpy.frame_for_serial.connect(self.video_panel.set_frame_for)
        self.context.scrcpy.state_changed.connect(self._on_scrcpy_state)
        self.context.scrcpy.error.connect(self._on_scrcpy_error)
        self.context.scrcpy.control_ready.connect(self._on_video_connected)
        self.video_panel.reconnect.connect(self._reconnect_video)
        self.video_panel.disconnect_requested.connect(self._disconnect_video)
        self.video_panel.open_window.connect(self._open_control_window)
        self.video_panel.toggle_preview.connect(self._toggle_preview)

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.context, self)
        dialog.exec()

    def _open_project_page(self) -> None:
        QDesktopServices.openUrl(QUrl(PROJECT_URL))

    def _on_config_changed(self) -> None:
        config = self.context.config
        self.device_poll_timer.setInterval(
            max(200, int(config.device_poll_ms))
        )
        self.startup_probe_timer.setInterval(
            max(200, int(config.device_poll_ms))
        )
        self._apply_theme(config.theme)
        for key, action in self.theme_actions.items():
            action.setChecked(key == config.theme)
        if self._allow_polling:
            if config.auto_refresh_devices:
                if not self.device_poll_timer.isActive():
                    self.device_poll_timer.start()
                    QTimer.singleShot(0, self.refresh_devices)
            else:
                self.device_poll_timer.stop()
        device = self.context.current_device
        if (
            self._preview_enabled
            and config.auto_start_preview
            and device is not None
            and device.connected
            and self.context.scrcpy.state in {"空闲", "已停止", "错误"}
        ):
            self.context.scrcpy.start(device.serial)
        self._update_preview_idle_timer()

    def _toggle_preview(self) -> None:
        if self._preview_enabled:
            self._set_preview_enabled(False)
            self.context.status.info("预览已关闭")
            return
        self._set_preview_enabled(True)
        self.context.status.info("预览已启用")

    def _set_preview_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        self._preview_enabled = enabled
        self.video_panel.set_preview_enabled(enabled)
        if not enabled:
            self._preview_idle_timer.stop()
            if (
                self.context.scrcpy.state in PREVIEW_ACTIVE_STATES
                or self.context.scrcpy.server is not None
            ):
                self.context.scrcpy.stop()
            return
        device = self.context.current_device
        if (
            device is not None
            and device.connected
            and self.context.scrcpy.state not in PREVIEW_ACTIVE_STATES
        ):
            self.context.scrcpy.start(device.serial)
        self._reset_preview_idle_timer()

    def _on_scrcpy_state(self, state: str) -> None:
        self.video_panel.set_state(state)
        if (
            self._preview_enabled
            and state in PREVIEW_ACTIVE_STATES
            and self.context.config.preview_auto_close_enabled
        ):
            self._reset_preview_idle_timer()
        else:
            self._preview_idle_timer.stop()

    def _preview_idle_ms(self) -> int:
        return max(10, int(self.context.config.preview_auto_close_seconds)) * 1000

    def _reset_preview_idle_timer(self) -> None:
        if (
            not self._preview_enabled
            or not self.context.config.preview_auto_close_enabled
            or self.context.scrcpy.state not in PREVIEW_ACTIVE_STATES
        ):
            self._preview_idle_timer.stop()
            return
        self._preview_idle_timer.start(self._preview_idle_ms())

    def _update_preview_idle_timer(self) -> None:
        self._reset_preview_idle_timer()

    def _auto_close_preview(self) -> None:
        if not self._preview_enabled:
            return
        if self.context.scrcpy.state not in PREVIEW_ACTIVE_STATES:
            return
        self._set_preview_enabled(False)
        timeout = max(10, int(self.context.config.preview_auto_close_seconds))
        if timeout % 60 == 0:
            duration = f"{timeout // 60} 分钟"
        else:
            duration = f"{timeout} 秒"
        self.context.status.info(
            f"已超过 {duration} 未操作，预览已自动关闭"
        )

    def eventFilter(self, watched, event) -> bool:
        if (
            event.type() in PREVIEW_ACTIVITY_EVENTS
            and self._preview_idle_timer.isActive()
        ):
            self._reset_preview_idle_timer()
        return super().eventFilter(watched, event)

    def _apply_initial_theme(self) -> None:
        mode = self.context.config.theme
        self._apply_theme(mode)
        for key, action in self.theme_actions.items():
            action.setChecked(key == mode)

    def _apply_theme(self, mode: str) -> None:
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, mode)

    def set_theme(self, mode: str) -> None:
        if mode not in {"light", "dark", "system"}:
            return
        self.context.config.theme = mode
        self.context.config_store.save(self.context.config)
        self._apply_theme(mode)
        for key, action in self.theme_actions.items():
            action.setChecked(key == mode)
        self.context.status.success(f"主题已切换为 {self.theme_actions[mode].text()}")

    def refresh_devices(self) -> None:
        self.context.request_show_hidden_on_refresh()
        self.context.device_service.refresh()

    def _on_device_visibility_changed(self) -> None:
        self._devices_signature = None
        self._on_devices_changed(self.context.devices)

    def _poll_devices(self) -> None:
        if self.context.device_service.busy:
            return
        self._quiet_refresh = True
        self.context.device_service.refresh(record=False)
        if not self.fastboot_service.busy:
            self.fastboot_service.refresh()

    def _start_startup_probe(self) -> None:
        self._resume_poll_after_probe = self.device_poll_timer.isActive()
        if self._resume_poll_after_probe:
            self.device_poll_timer.stop()
        self._probe_for_devices()
        if not self._has_any_device():
            self.startup_probe_timer.start()

    def _probe_for_devices(self) -> None:
        if self._has_any_device():
            self._stop_startup_probe_if_ready()
            return
        if not self.context.device_service.busy:
            self._quiet_refresh = True
            self.context.device_service.refresh(record=False)
        if not self.fastboot_service.busy:
            self.fastboot_service.refresh()

    def _has_any_device(self) -> bool:
        return bool(self.context.devices or self._fastboot_devices)

    def _stop_startup_probe_if_ready(self) -> None:
        if not self._has_any_device():
            return
        self.startup_probe_timer.stop()
        if self._resume_poll_after_probe:
            self._resume_poll_after_probe = False
            if self.context.config.auto_refresh_devices:
                self.device_poll_timer.start()

    def _on_refresh_started(self) -> None:
        if not self._quiet_refresh:
            self.context.status.info("正在刷新设备列表…")

    def _track_new_devices(self, devices: list[DeviceInfo]) -> list[DeviceInfo]:
        serials = {device.serial for device in devices}
        if self._known_serials is None:
            self._known_serials = serials
            return []
        added = [device for device in devices if device.serial not in self._known_serials]
        self._known_serials = serials
        return added

    def _notify_new_devices(self, devices: list[DeviceInfo]) -> None:
        if not devices:
            return
        parts = [
            f"{device.display_name}（{self._connection_kind(device)}）"
            for device in devices
        ]
        detail = "、".join(parts) + " 已连接"
        self.toast.show_message(detail, 2000)
        self._position_toast()
        self.toast.raise_()

    @staticmethod
    def _connection_kind(device: DeviceInfo) -> str:
        serial = device.serial or ""
        if ":" in serial or "adb-tls" in serial or "._adb" in serial:
            return "无线"
        return "USB"

    def _append_fastboot_items(self) -> None:
        existing = set()
        for index in range(self.device_combo.count()):
            data = self.device_combo.itemData(index)
            if data is not None:
                existing.add(data.serial)
        for device in self._fastboot_devices:
            if device.serial in existing:
                continue
            if self.context.is_device_hidden(device.serial):
                continue
            info = DeviceInfo(
                serial=device.serial,
                state="fastboot",
                model=device.serial,
            )
            self.device_combo.addItem(
                f"{device.serial}  [fastboot]  Fastboot",
                info,
            )

    def _on_fastboot_devices(self, devices) -> None:
        available = list(devices)
        signature = tuple((device.serial, device.detail) for device in available)
        previous_signature = tuple(
            (device.serial, device.detail) for device in self._fastboot_devices
        )
        serials = {device.serial for device in available}
        added: list[FastbootDevice] = []
        if self._known_fastboot is None:
            self._known_fastboot = serials
        else:
            added = [
                device
                for device in available
                if device.serial not in self._known_fastboot
            ]
            self._known_fastboot = serials
        if signature == previous_signature:
            # Unchanged fastboot results must not rebuild the selector or
            # re-apply the current device every 2.5 s.
            return
        self._fastboot_devices = available
        self.context.set_fastboot_devices(available)
        if added:
            detail = "、".join(f"{device.serial}（Fastboot）" for device in added)
            self.toast.show_message(f"{detail} 已连接", 2000)
            self._position_toast()
            self.toast.raise_()
        self._devices_signature = None
        self._on_devices_changed(self.context.devices)
        self._stop_startup_probe_if_ready()

    def _on_fastboot_failed(self, _message: str) -> None:
        pass

    def _position_toast(self) -> None:
        toast = getattr(self, "toast", None)
        if toast is None or not toast.isVisible():
            return
        parent = self.centralWidget()
        if parent is None:
            return
        x = max(12, parent.width() - toast.width() - 24)
        toast.move(x, 60)

    def _on_devices_changed(self, devices: list[DeviceInfo]) -> None:
        self._quiet_refresh = False
        active_serials = {
            device.serial
            for device in devices
            if device.connected
        }
        active_serials.update(
            device.serial for device in self._fastboot_devices
        )
        if self.context.consume_show_hidden_on_refresh(active_serials):
            self._devices_signature = None
            # A manual refresh restores USB devices that were disconnected in
            # the app. Wireless devices stay disconnected until adb connect.
            if self.context.reconnect_usb_devices(devices):
                self._devices_signature = None
        signature = tuple(
            (device.serial, device.state, device.model, device.transport_id)
            for device in devices
        )
        if self._devices_signature == signature:
            return
        self._devices_signature = signature
        visible = [
            device
            for device in devices
            if not self.context.is_device_hidden(device.serial)
            and not self.context.is_device_disconnected(device.serial)
        ]
        added = self._track_new_devices(visible)
        self._prune_control_windows(devices)
        previous_serial = self.context.current_device.serial if self.context.current_device else ""
        selected_serial = previous_serial or self.context.config.default_serial

        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        if not visible:
            if not any(
                not self.context.is_device_hidden(device.serial)
                for device in self._fastboot_devices
            ):
                self.device_combo.addItem("未连接设备", None)
        else:
            for device in visible:
                state = STATE_TEXT.get(device.state, device.state)
                self.device_combo.addItem(
                    f"{device.display_name}  [{device.serial}]  {state}",
                    device,
                )
        self._append_fastboot_items()
        self.device_combo.blockSignals(False)

        if not visible:
            self._select_device(None)
            if self.device_combo.count():
                self.device_combo.setCurrentIndex(0)
                self._select_device(self.device_combo.itemData(0))
            self.context.set_devices(devices)
            self.connection_label.setText("未连接")
            self.status_summary.setText("未连接设备")
            self.context.status.info("未发现已连接设备")
            self._notify_new_devices(added)
            self._stop_startup_probe_if_ready()
            return

        index = 0
        for i in range(self.device_combo.count()):
            device = self.device_combo.itemData(i)
            if device and device.serial == selected_serial:
                index = i
                break
        self.device_combo.setCurrentIndex(index)
        self._select_device(self.device_combo.itemData(index))
        self.context.set_devices(devices)
        self._notify_new_devices(added)
        self._stop_startup_probe_if_ready()

    def _on_refresh_failed(self, message: str) -> None:
        self.context.cancel_show_hidden_on_refresh()
        quiet = self._quiet_refresh
        self._quiet_refresh = False
        if quiet:
            return
        self.connection_label.setText("刷新失败")
        self.context.status.error(message)

    def _on_combo_changed(self, index: int) -> None:
        if index < 0:
            return
        self._select_device(self.device_combo.itemData(index))

    def _select_device(self, device: DeviceInfo | None) -> None:
        if device is not None and (
            self.context.is_device_hidden(device.serial)
            or self.context.is_device_disconnected(device.serial)
        ):
            return
        previous_metrics_serial = self.context.metrics.serial
        previous_video_serial = self.context.scrcpy.serial
        self.context.set_current_device(device)
        serial = device.serial if device is not None and device.connected else ""
        if previous_video_serial and previous_video_serial != serial:
            self.context.scrcpy.stop()
        if serial != self.video_panel.device_serial:
            self.video_panel.set_device(serial or None)
        if (
            self._preview_enabled
            and serial
            and (
                serial != previous_video_serial
                or self.context.scrcpy.state not in PREVIEW_ACTIVE_STATES
            )
            and self.context.config.auto_start_preview
        ):
            self.context.scrcpy.start(serial)
        if serial != previous_metrics_serial:
            self.metrics_panel.clear()
        self.context.metrics.set_device(
            serial or None,
            self.context.config.metrics_interval_ms,
        )
        self.connection_label.setText(
            f"{device.display_name}（{device.serial}）" if device else "未连接"
        )
        self.status_summary.setText(
            f"设备：{device.serial}  {STATE_TEXT.get(device.state, device.state)}"
            if device
            else "未连接设备"
        )
        if device is not None and self.device_combo.currentData() != device:
            self.device_combo.blockSignals(True)
            for i in range(self.device_combo.count()):
                candidate = self.device_combo.itemData(i)
                if candidate and candidate.serial == device.serial:
                    self.device_combo.setCurrentIndex(i)
                    break
            self.device_combo.blockSignals(False)
        page = self.stack.currentWidget()
        if isinstance(page, BasePage):
            page.on_device_changed(device)

    def _on_nav_changed(self, row: int) -> None:
        if row < 0:
            return
        old = self.stack.currentWidget()
        if isinstance(old, BasePage):
            old.on_deactivated()
        self.stack.setCurrentIndex(row)
        page = self.stack.widget(row)
        if isinstance(page, BasePage):
            page.on_activated()
            page.on_device_changed(self.context.current_device)

    def _on_status_message(self, text: str, level: str) -> None:
        self.status_message.setText(text)
        if level == "error":
            self.status_message.setObjectName("StatusError")
        elif level == "success":
            self.status_message.setObjectName("StatusSuccess")
        else:
            self.status_message.setObjectName("Muted")
        self.status_message.style().unpolish(self.status_message)
        self.status_message.style().polish(self.status_message)

    def _on_metrics_failed(self, message: str) -> None:
        self.context.status.error(f"性能采样失败：{message}")

    def _reconnect_video(self) -> None:
        if not self._preview_enabled:
            self.context.status.info("预览已关闭，请先启用预览")
            return
        device = self.context.current_device
        if device is None or not device.connected:
            self.context.status.error("请先选择已连接的设备")
            return
        if self.context.scrcpy.state in PREVIEW_ACTIVE_STATES:
            return
        self.context.scrcpy.start(device.serial)
        self.context.status.info(f"正在连接视频：{device.serial}")

    def _disconnect_video(self) -> None:
        self.context.scrcpy.stop()
        self.video_panel.set_state("已停止")
        self.context.status.info("视频连接已断开")

    def _open_control_window(self) -> None:
        device = self.context.current_device
        if device is None or not device.connected:
            self.context.status.error("请先选择已连接的设备")
            return
        serial = device.serial
        self.device_dock.show()
        self.device_dock.raise_()
        self.video_panel.show()
        window = self.control_windows.get(serial)
        if window is None:
            window = ControlWindow(self.context)
            window.closed.connect(
                lambda s=serial: self._on_control_window_closed(s)
            )
            self.control_windows[serial] = window
        window.show_for(serial)
        window.raise_()
        window.activateWindow()
        self.context.status.info(f"正在打开独立控制窗口：{serial}")

    def _on_control_window_closed(self, serial: str) -> None:
        self.control_windows.pop(serial, None)

    def _prune_control_windows(self, devices: list[DeviceInfo]) -> None:
        connected = {device.serial for device in devices if device.connected}
        for serial, window in list(self.control_windows.items()):
            if (
                serial not in connected
                or self.context.is_device_disconnected(serial)
            ):
                window.close()

    def _on_scrcpy_error(self, message: str) -> None:
        self.video_panel.set_state(f"错误：{message}")
        self.context.status.error(f"视频：{message}")

    def _on_video_connected(self, info) -> None:
        fallback = f"{info.width}×{info.height}"
        self.context.status.success(f"视频已连接：{fallback}")
        serial = self.context.scrcpy.serial
        if not serial:
            return
        process = self.context.adb.shell(
            serial,
            "wm size",
            timeout_ms=5000,
            record=False,
        )
        process.finished.connect(
            lambda result, s=serial, f=fallback: self._apply_video_resolution(
                s, result, f
            )
        )

    def _apply_video_resolution(self, serial: str, result, fallback: str) -> None:
        if self.context.scrcpy.serial != serial:
            return
        if self.context.scrcpy.state not in {"等待视频", "已连接"}:
            return
        if not result.ok:
            return
        effective, _physical = parse_wm_size(result.stdout)
        if effective:
            self.context.status.success(f"视频已连接：{effective}")

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and not self.isMinimized():
            QTimer.singleShot(0, self.video_panel.refresh)
            QTimer.singleShot(0, self._position_toast)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        QTimer.singleShot(0, self._position_toast)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.device_poll_timer.stop()
        self.startup_probe_timer.stop()
        self._preview_idle_timer.stop()
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self.toast.timer.stop()
        for window in list(self.control_windows.values()):
            window.close()
        self.control_windows.clear()
        for page in self.pages:
            page.shutdown()
        self.context.shutdown()
        super().closeEvent(event)
