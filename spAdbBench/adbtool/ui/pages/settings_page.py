from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...infrastructure.parsers import DeviceInfo
from ...services.danger import get_danger
from ...services.settings import (
    SettingsService,
    display_command,
    format_number,
    validate_key,
    validate_value,
)
from ..page import BasePage
from ..widgets.danger_dialog import confirm_danger


ANIMATION_LABELS = (
    ("window_animation_scale", "窗口动画"),
    ("transition_animation_scale", "过渡动画"),
    ("animator_duration_scale", "属性动画"),
)
STATUS_ICONS = (
    ("clock", "时钟"),
    ("alarm", "闹钟"),
    ("bluetooth", "蓝牙"),
    ("wifi", "Wi-Fi"),
    ("mobile", "移动信号"),
    ("battery", "电池"),
    ("volume", "音量"),
    ("rotate", "旋转锁定"),
    ("location", "定位"),
    ("sync", "同步"),
    ("headset", "耳机"),
    ("cast", "投屏"),
)

TABLE_LABELS = (
    ("global", "Global"),
    ("secure", "Secure"),
    ("system", "System"),
)

READ_FIELDS = (
    ("system", "font_scale", "font"),
    ("global", "window_animation_scale", "animation"),
    ("global", "transition_animation_scale", "animation"),
    ("global", "animator_duration_scale", "animation"),
    ("system", "screen_off_timeout", "timeout"),
    ("global", "policy_control", "immersive"),
    ("secure", "icon_blacklist", "icons"),
)


class SettingsPage(BasePage):
    def __init__(self, context) -> None:
        super().__init__(context)
        self.service = SettingsService(context.adb, context.settings_history)
        self._serial = ""
        self._loaded_serial = ""
        self._epoch = 0
        self._read_queue: list[tuple[str, str, str]] = []
        self._read_process = None
        self._hidden_process = None
        self._write_process = None
        self._last_values: dict[tuple[str, str], str] = {}
        self._unknown_icons: list[str] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        scroll.setWidget(content)
        root.addWidget(scroll)

        header = QHBoxLayout()
        heading = QLabel("系统设置")
        heading.setObjectName("SectionTitle")
        self.message_label = QLabel("选择设备后读取系统设置。")
        self.message_label.setObjectName("Muted")
        self.refresh_button = QPushButton("刷新设置")
        header.addWidget(heading)
        header.addSpacing(12)
        header.addWidget(self.message_label, 1)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        layout.addWidget(self._build_display_group())
        layout.addWidget(self._build_icons_group())
        layout.addWidget(self._build_hidden_group())
        layout.addStretch(1)

        self.refresh_button.clicked.connect(self._load_all)
        self.apply_font.clicked.connect(self._apply_font)
        self.reset_font.clicked.connect(self._reset_font)
        self.apply_animation.clicked.connect(self._apply_animation)
        self.reset_animation.clicked.connect(self._reset_animation)
        self.apply_timeout.clicked.connect(self._apply_timeout)
        self.apply_immersive.clicked.connect(self._apply_immersive)
        self.apply_icons.clicked.connect(self._apply_icons)
        self.all_icons_button.clicked.connect(self._select_all_icons)
        self.clear_icons_button.clicked.connect(self._clear_icons)
        self.read_hidden.clicked.connect(self._read_hidden)
        self.write_hidden.clicked.connect(self._write_hidden)
        self.hidden_key.returnPressed.connect(self._read_hidden)
        self.hidden_value.returnPressed.connect(self._write_hidden)
        self.hidden_table.currentIndexChanged.connect(self._update_hidden_buttons)
        self.hidden_key.textChanged.connect(self._update_hidden_buttons)
        self.hidden_value.textChanged.connect(self._update_hidden_buttons)

        self._update_controls()

    def _build_display_group(self) -> QGroupBox:
        group = QGroupBox("显示与动画")
        layout = QGridLayout(group)
        layout.setContentsMargins(0, 10, 0, 6)
        layout.setHorizontalSpacing(16)
        layout.setVerticalSpacing(12)
        layout.setColumnMinimumWidth(0, 84)

        self.font_scale = QDoubleSpinBox()
        self.font_scale.setRange(0.5, 3.0)
        self.font_scale.setSingleStep(0.05)
        self.font_scale.setDecimals(2)
        self.font_scale.setValue(1.0)
        self.font_scale.setMaximumWidth(92)
        self.font_slider = QSlider(Qt.Orientation.Horizontal)
        self.font_slider.setRange(0, 1000)
        self.font_slider.setPageStep(50)
        self.font_slider.setSingleStep(5)
        self._link_curve(
            self.font_scale,
            self.font_slider,
            minimum=0.5,
            maximum=3.0,
            default=1.0,
            decimals=2,
        )
        self.apply_font = QPushButton("应用字体")
        self.apply_font.setObjectName("Primary")
        self.reset_font = QPushButton("恢复字体")
        font_row = QHBoxLayout()
        font_row.setContentsMargins(0, 0, 0, 0)
        font_row.setSpacing(12)
        font_row.addWidget(self.font_slider, 1)
        font_row.addWidget(self.font_scale)
        font_limit = QLabel("倍（上限 3.0）")
        font_limit.setObjectName("Muted")
        font_row.addWidget(font_limit)
        layout.addWidget(QLabel("字体倍率"), 0, 0)
        layout.addLayout(font_row, 0, 1)
        layout.addWidget(self.apply_font, 0, 2)
        layout.addWidget(self.reset_font, 0, 3)

        self.animation_spins: dict[str, QDoubleSpinBox] = {}
        self.animation_sliders: dict[str, QSlider] = {}
        self.animation_reset_buttons: list[QPushButton] = []
        row = 1
        for key, label in ANIMATION_LABELS:
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 10.0)
            spin.setSingleStep(0.5)
            spin.setDecimals(1)
            spin.setValue(1.0)
            spin.setMaximumWidth(92)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 1000)
            slider.setPageStep(50)
            slider.setSingleStep(5)
            self._link_curve(
                spin,
                slider,
                minimum=0.0,
                maximum=10.0,
                default=1.0,
                decimals=1,
            )
            self.animation_spins[key] = spin
            self.animation_sliders[key] = slider
            animation_row = QHBoxLayout()
            animation_row.setContentsMargins(0, 0, 0, 0)
            animation_row.setSpacing(12)
            animation_row.addWidget(slider, 1)
            animation_row.addWidget(spin)
            animation_limit = QLabel("倍（上限 10.0）")
            animation_limit.setObjectName("Muted")
            animation_row.addWidget(animation_limit)
            reset_single = QPushButton("恢复默认")
            reset_single.setToolTip(
                f"将{label}恢复为默认值 1.0；点击「应用动画」后写入设备"
            )
            reset_single.clicked.connect(
                lambda _checked=False, s=spin: self._reset_animation_value(s)
            )
            self.animation_reset_buttons.append(reset_single)
            animation_row.addWidget(reset_single)
            layout.addWidget(QLabel(label), row, 0)
            layout.addLayout(animation_row, row, 1)
            row += 1

        self.apply_animation = QPushButton("应用动画")
        self.apply_animation.setObjectName("Primary")
        self.reset_animation = QPushButton("恢复动画")
        layout.addWidget(self.apply_animation, row, 2)
        layout.addWidget(self.reset_animation, row, 3)
        row += 1

        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(0, 65535)
        self.timeout_spin.setSpecialValueText("不熄屏")
        self.timeout_spin.setValue(30)
        self.timeout_spin.setMaximumWidth(100)
        self.timeout_slider = QSlider(Qt.Orientation.Horizontal)
        self.timeout_slider.setRange(0, 1000)
        self.timeout_slider.setPageStep(50)
        self.timeout_slider.setSingleStep(5)
        self._link_curve(
            self.timeout_spin,
            self.timeout_slider,
            minimum=0,
            maximum=65535,
            default=30,
            decimals=0,
        )
        self.apply_timeout = QPushButton("应用锁屏")
        timeout_row = QHBoxLayout()
        timeout_row.setContentsMargins(0, 0, 0, 0)
        timeout_row.setSpacing(12)
        timeout_row.addWidget(self.timeout_slider, 1)
        timeout_row.addWidget(self.timeout_spin)
        timeout_limit = QLabel("秒（上限 65535）")
        timeout_limit.setObjectName("Muted")
        timeout_row.addWidget(timeout_limit)
        layout.addWidget(QLabel("自动锁屏"), row, 0)
        layout.addLayout(timeout_row, row, 1)
        layout.addWidget(self.apply_timeout, row, 2)
        row += 1

        self.immersive_check = QCheckBox("沉浸模式（隐藏状态栏与导航栏）")
        self.apply_immersive = QPushButton("应用沉浸")
        layout.addWidget(self.immersive_check, row, 0, 1, 2)
        layout.addWidget(self.apply_immersive, row, 2)
        layout.setColumnStretch(1, 1)

        note = QLabel("修改记录会用于配置快照。")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note, row + 1, 0, 1, 4)
        return group

    def _build_icons_group(self) -> QGroupBox:
        self.icons_group = QGroupBox("隐藏状态栏图标")
        group = self.icons_group
        layout = QGridLayout(group)
        layout.setContentsMargins(0, 8, 0, 4)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(10)

        self.icon_checks: dict[str, QCheckBox] = {}
        for index, (key, label) in enumerate(STATUS_ICONS):
            check = QCheckBox(label)
            self.icon_checks[key] = check
            layout.addWidget(check, index // 3, index % 3)

        rows = (len(STATUS_ICONS) + 2) // 3
        self.other_icons_label = QLabel("其他已隐藏的系统图标：无")
        self.other_icons_label.setObjectName("Muted")
        self.other_icons_label.setWordWrap(True)
        layout.addWidget(self.other_icons_label, rows, 0, 1, 3)

        self.icons_note = QLabel("勾选隐藏，取消恢复。")
        self.icons_note.setObjectName("Muted")
        self.icons_note.setWordWrap(True)
        layout.addWidget(self.icons_note, rows + 1, 0, 1, 3)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)
        self.apply_icons = QPushButton("应用隐藏设置")
        self.apply_icons.setObjectName("Primary")
        self.all_icons_button = QPushButton("全部隐藏")
        self.clear_icons_button = QPushButton("全部显示")
        button_row.addWidget(self.apply_icons)
        button_row.addWidget(self.all_icons_button)
        button_row.addWidget(self.clear_icons_button)
        button_row.addStretch(1)
        layout.addLayout(button_row, rows + 2, 0, 1, 3)
        return group

    def _build_hidden_group(self) -> QGroupBox:
        group = QGroupBox("隐藏设置")
        layout = QGridLayout(group)
        layout.setContentsMargins(0, 8, 0, 4)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(10)

        self.hidden_table = QComboBox()
        for table, label in TABLE_LABELS:
            self.hidden_table.addItem(label, table)
        self.hidden_key = QLineEdit()
        self.hidden_key.setPlaceholderText("设置键，例如 icon_blacklist")
        self.read_hidden = QPushButton("读取")
        self.current_value = QLineEdit()
        self.current_value.setReadOnly(True)
        self.current_value.setPlaceholderText("读取结果")
        self.hidden_value = QLineEdit()
        self.hidden_value.setPlaceholderText("写入值；留空不写入")
        self.write_hidden = QPushButton("写入")
        self.write_hidden.setObjectName("Primary")

        layout.addWidget(QLabel("设置表"), 0, 0)
        layout.addWidget(self.hidden_table, 0, 1)
        layout.addWidget(QLabel("键"), 0, 2)
        layout.addWidget(self.hidden_key, 0, 3)
        layout.addWidget(self.read_hidden, 0, 4)
        layout.addWidget(QLabel("当前值"), 1, 0)
        layout.addWidget(self.current_value, 1, 1, 1, 4)
        layout.addWidget(QLabel("写入值"), 2, 0)
        layout.addWidget(self.hidden_value, 2, 1, 1, 3)
        layout.addWidget(self.write_hidden, 2, 4)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(3, 2)

        history_label = QLabel("本机最近修改")
        history_label.setObjectName("Muted")
        self.history_table = QTableWidget(0, 4)
        self.history_table.setHorizontalHeaderLabels(["时间", "表", "键", "值"])
        self.history_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.history_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.history_table.setAlternatingRowColors(True)
        self.history_table.verticalHeader().setVisible(False)
        history_header = self.history_table.horizontalHeader()
        history_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        history_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        history_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        history_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.history_table.setMinimumHeight(110)
        self.history_table.setMaximumHeight(170)

        layout.addWidget(history_label, 3, 0, 1, 5)
        layout.addWidget(self.history_table, 4, 0, 1, 5)
        return group

    def on_activated(self) -> None:
        self._update_controls()

    def on_device_changed(self, device: DeviceInfo | None) -> None:
        self._set_device(device, refresh=True)

    def on_deactivated(self) -> None:
        self._cancel_reads()

    def shutdown(self) -> None:
        self._cancel_reads()
        if self._write_process is not None and self._write_process.is_running:
            self._write_process.cancel()

    def _set_device(self, device: DeviceInfo | None, refresh: bool) -> None:
        serial = device.serial if device and device.connected else ""
        if serial == self._serial:
            if refresh and serial and self._loaded_serial != serial:
                self._load_all()
            return

        self._serial = serial
        self._cancel_reads()
        self._loaded_serial = ""
        self._last_values.clear()
        self._set_defaults()
        self._load_history()
        if serial:
            self.message_label.setText(f"当前设备：{serial}")
            if refresh:
                self._load_all()
        else:
            self.message_label.setText("未选择设备。")
        self._update_controls()

    def _set_defaults(self) -> None:
        for widget in (
            self.font_scale,
            self.timeout_spin,
            *self.animation_spins.values(),
        ):
            widget.blockSignals(True)
        self.font_scale.setValue(1.0)
        self.timeout_spin.setValue(30)
        for spin in self.animation_spins.values():
            spin.setValue(1.0)
        for widget in (
            self.font_scale,
            self.timeout_spin,
            *self.animation_spins.values(),
        ):
            widget.blockSignals(False)
        self.immersive_check.setChecked(False)
        for check in self.icon_checks.values():
            check.setChecked(False)
        self._unknown_icons = []
        self._update_other_icons_label()
        self.current_value.clear()
        self.hidden_value.clear()

    def _load_all(self) -> None:
        if not self._serial:
            self.context.status.error("请先连接设备")
            return
        self._cancel_reads()
        self._epoch += 1
        self._read_queue = list(READ_FIELDS)
        self._loaded_serial = ""
        self.refresh_button.setEnabled(False)
        self.message_label.setText("正在读取系统设置…")
        self._read_next()

    def _cancel_reads(self) -> None:
        self._read_queue = []
        for process in (self._read_process, self._hidden_process):
            if process is not None and process.is_running:
                process.cancel()
        self._read_process = None
        self._hidden_process = None
        self.refresh_button.setEnabled(True)

    def _read_next(self) -> None:
        if not self._serial:
            return
        if not self._read_queue:
            self._loaded_serial = self._serial
            self.refresh_button.setEnabled(True)
            self.message_label.setText(f"当前设备：{self._serial}")
            self.context.status.success("系统设置已读取")
            return
        table, key, kind = self._read_queue.pop(0)
        serial = self._serial
        epoch = self._epoch
        process = self.service.get(serial, table, key)
        self._read_process = process
        process.finished.connect(
            lambda result, s=serial, e=epoch, t=table, k=key, kind=kind: (
                self._on_read_finished(s, e, t, k, kind, result)
            )
        )

    def _on_read_finished(
        self,
        serial: str,
        epoch: int,
        table: str,
        key: str,
        kind: str,
        result,
    ) -> None:
        if serial != self._serial or epoch != self._epoch:
            return
        self._read_process = None
        if result.ok:
            value = result.stdout.strip()
            self._last_values[(table, key)] = value
            self._apply_read_value(kind, key, value)
        else:
            self.message_label.setText(
                f"读取 {table}/{key} 失败：{(result.stderr or result.stdout).strip()}"
            )
        self._read_next()

    def _apply_read_value(self, kind: str, key: str, value: str) -> None:
        missing = value in {"", "null", "None"}
        if kind == "font":
            if not missing:
                try:
                    self._set_spin(self.font_scale, float(value), 0.5, 3.0)
                except ValueError:
                    self.message_label.setText(f"字体倍率不可读：{value}")
        elif kind == "animation":
            if not missing:
                try:
                    self._set_spin(self.animation_spins[key], float(value), 0.0, 10.0)
                except ValueError:
                    pass
        elif kind == "timeout":
            if not missing:
                try:
                    seconds = int(value) / 1000
                    self._set_spin(self.timeout_spin, seconds, 0, 65535)
                except ValueError:
                    pass
        elif kind == "immersive":
            self.immersive_check.setChecked(not missing and "immersive" in value)
        elif kind == "icons":
            selected: list[str] = []
            if not missing:
                selected = [
                    item.strip() for item in value.split(",") if item.strip()
                ]
            selected_set = set(selected)
            for icon, check in self.icon_checks.items():
                check.setChecked(icon in selected_set)
            self._unknown_icons = [
                icon for icon in selected if icon not in self.icon_checks
            ]
            self._update_other_icons_label()

    @staticmethod
    def _link_curve(
        spin,
        slider: QSlider,
        *,
        minimum: float,
        maximum: float,
        default: float,
        decimals: int,
    ) -> None:
        """Map the slider non-linearly: default sits left of center, speed grows."""
        span = float(maximum) - float(minimum)
        default_ratio = (float(default) - float(minimum)) / span
        default_ratio = min(max(default_ratio, 1e-6), 1 - 1e-6)
        exponent = math.log(default_ratio) / math.log(0.35)

        def to_position(value: float) -> int:
            ratio = (float(value) - float(minimum)) / span
            ratio = min(1.0, max(0.0, ratio))
            return round(1000 * (ratio ** (1.0 / exponent)))

        def to_value(position: int) -> float:
            ratio = min(1.0, max(0.0, float(position) / 1000.0))
            value = float(minimum) + span * (ratio ** exponent)
            return round(value, decimals) if decimals else int(round(value))

        spin._curve_to_pos = to_position
        spin._linked_slider = slider
        spin.valueChanged.connect(
            lambda value, s=slider: s.setValue(to_position(value))
        )
        slider.valueChanged.connect(
            lambda position, sp=spin: sp.setValue(to_value(position))
        )
        slider.setValue(to_position(spin.value()))

    @staticmethod
    def _set_spin(spin, value: float, minimum: float, maximum: float) -> None:
        clamped = max(minimum, min(maximum, value))
        spin.blockSignals(True)
        spin.setValue(clamped)
        spin.blockSignals(False)
        slider = getattr(spin, "_linked_slider", None)
        if slider is not None:
            to_position = getattr(spin, "_curve_to_pos", None)
            if to_position is not None:
                slider.blockSignals(True)
                slider.setValue(to_position(clamped))
                slider.blockSignals(False)

    def _format_current(self, table: str, key: str) -> str:
        value = self._last_values.get((table, key), "")
        return "未设置" if value in {"", "null", "None"} else value

    def _confirm(self, spec) -> bool:
        return confirm_danger(self, spec)

    def _apply_font(self) -> None:
        if not self._serial:
            return
        value = self.font_scale.value()
        command = f"settings put system font_scale {format_number(value)}"
        spec = get_danger(
            "settings.font_scale",
            command=command,
            detail=(
                f"当前值：{self._format_current('system', 'font_scale')} → "
                f"{format_number(value)}"
            ),
        )
        if not self._confirm(spec):
            return
        process = self.service.set_font_scale(self._serial, value)
        self._track_write(process, "字体倍率")

    def _reset_font(self) -> None:
        self._set_spin(self.font_scale, 1.0, 0.5, 3.0)
        self._apply_font()

    def _apply_animation(self) -> None:
        if not self._serial:
            return
        commands = [
            f"settings put global {key} {format_number(spin.value())}"
            for key, spin in self.animation_spins.items()
        ]
        spec = get_danger(
            "settings.animation",
            command="\n".join(commands),
            detail="同时应用窗口、过渡和属性动画倍率；0 表示关闭动画。",
        )
        if not self._confirm(spec):
            return
        for key, spin in self.animation_spins.items():
            process = self.service.set_animation_scale(
                self._serial, key, spin.value()
            )
            self._track_write(process, "动画倍率")

    def _reset_animation_value(self, spin: QDoubleSpinBox) -> None:
        self._set_spin(spin, 1.0, 0.0, 10.0)

    def _reset_animation(self) -> None:
        for spin in self.animation_spins.values():
            self._set_spin(spin, 1.0, 0.0, 10.0)
        self._apply_animation()

    def _apply_timeout(self) -> None:
        if not self._serial:
            return
        seconds = self.timeout_spin.value()
        command = f"settings put system screen_off_timeout {seconds * 1000}"
        target = "不熄屏（0 毫秒）" if seconds == 0 else f"{seconds * 1000} 毫秒（{seconds} 秒）"
        spec = get_danger(
            "settings.write_system",
            command=command,
            detail=(
                f"自动锁屏时间：{self._format_current('system', 'screen_off_timeout')} "
                f"→ {target}"
            ),
        )
        if not self._confirm(spec):
            return
        process = self.service.set_screen_timeout(self._serial, seconds)
        self._track_write(process, "自动锁屏时间")

    def _apply_immersive(self) -> None:
        if not self._serial:
            return
        enabled = self.immersive_check.isChecked()
        value = "immersive.full=*" if enabled else "null"
        command = f"settings put global policy_control {value}"
        spec = get_danger(
            "settings.write_global",
            command=command,
            detail=(
                "开启后隐藏状态栏与导航栏；关闭时写入 null 恢复系统策略。"
                if enabled
                else "关闭沉浸模式，恢复系统默认状态栏与导航栏。"
            ),
        )
        if not self._confirm(spec):
            return
        process = self.service.set_immersive(self._serial, enabled)
        self._track_write(process, "沉浸模式")

    def _apply_icons(self) -> None:
        if not self._serial:
            return
        icons = [
            key for key, check in self.icon_checks.items() if check.isChecked()
        ]
        icons.extend(self._unknown_icons)
        value = ",".join(icons) if icons else "null"
        command = display_command("secure", "icon_blacklist", value)
        spec = get_danger(
            "settings.write_secure",
            command=command,
            detail="状态栏图标隐藏列表；空列表写入 null，恢复全部图标。",
        )
        if not self._confirm(spec):
            return
        process = self.service.set_icon_blacklist(self._serial, icons)
        self._track_write(process, "状态栏图标")

    def _select_all_icons(self) -> None:
        for check in self.icon_checks.values():
            check.setChecked(True)

    def _clear_icons(self) -> None:
        for check in self.icon_checks.values():
            check.setChecked(False)
        self._unknown_icons = []
        self._update_other_icons_label()

    def _update_other_icons_label(self) -> None:
        if self._unknown_icons:
            text = "其他已隐藏的系统图标：" + "、".join(self._unknown_icons) + "（应用时保留）"
        else:
            text = "其他已隐藏的系统图标：无"
        self.other_icons_label.setText(text)

    def _read_hidden(self) -> None:
        if not self._serial:
            self.context.status.error("请先连接设备")
            return
        table = self.hidden_table.currentData()
        try:
            key = validate_key(self.hidden_key.text())
        except ValueError as exc:
            self.message_label.setText(str(exc))
            return
        if self._hidden_process is not None and self._hidden_process.is_running:
            self._hidden_process.cancel()
        serial = self._serial
        epoch = self._epoch
        process = self.service.get(serial, table, key)
        self._hidden_process = process
        self.message_label.setText(f"正在读取 {table}/{key}…")
        process.finished.connect(
            lambda result, s=serial, e=epoch, t=table, k=key: (
                self._on_hidden_read(s, e, t, k, result)
            )
        )

    def _on_hidden_read(
        self,
        serial: str,
        epoch: int,
        table: str,
        key: str,
        result,
    ) -> None:
        if serial != self._serial or epoch != self._epoch:
            return
        self._hidden_process = None
        if not result.ok:
            self.message_label.setText(
                f"读取失败：{(result.stderr or result.stdout).strip()}"
            )
            self.context.status.error("读取隐藏设置失败")
            return
        value = result.stdout.strip()
        self._last_values[(table, key)] = value
        self.current_value.setText(value)
        self.message_label.setText(f"{table}/{key} 已读取")
        self.context.status.success("隐藏设置已读取")

    def _write_hidden(self) -> None:
        if not self._serial:
            self.context.status.error("请先连接设备")
            return
        table = self.hidden_table.currentData()
        try:
            key = validate_key(self.hidden_key.text())
            value = validate_value(self.hidden_value.text())
        except ValueError as exc:
            self.message_label.setText(str(exc))
            return
        command = display_command(table, key, value)
        danger_key = {
            "global": "settings.write_global",
            "secure": "settings.write_secure",
            "system": "settings.write_system",
        }[table]
        spec = get_danger(
            danger_key,
            command=command,
            detail=(
                f"表：{table}；键：{key}；"
                f"当前值：{self._format_current(table, key)} → 新值：{value}"
            ),
        )
        if not self._confirm(spec):
            return
        process = self.service.put(self._serial, table, key, value)
        self._track_write(
            process,
            f"隐藏设置 {table}/{key}",
            lambda: self._on_hidden_written(table, key, value),
        )

    def _on_hidden_written(self, table: str, key: str, value: str) -> None:
        self._last_values[(table, key)] = value
        self.current_value.setText(value)
        self._load_history()

    def _track_write(self, process, label: str, on_success=None) -> None:
        serial = self._serial
        self._write_process = process
        self.message_label.setText(f"正在写入{label}…")
        process.finished.connect(
            lambda result, s=serial, name=label, callback=on_success: (
                self._on_write_finished(s, name, result, callback)
            )
        )
        self._update_controls()

    def _on_write_finished(
        self,
        serial: str,
        label: str,
        result,
        on_success=None,
    ) -> None:
        self._write_process = None
        if serial != self._serial:
            return
        if result.cancelled:
            self.message_label.setText("写入已取消")
            self._update_controls()
            return
        if not result.ok:
            detail = (result.stderr or result.stdout).strip() or "未知错误"
            self.message_label.setText(f"{label}写入失败：{detail}")
            self.context.status.error(f"{label}写入失败：{detail}")
            self._update_controls()
            return
        self.message_label.setText(f"{label}已写入")
        self.context.status.success(f"{label}已写入")
        if on_success is not None:
            on_success()
        self._load_history()
        self._update_controls()

    def _load_history(self) -> None:
        entries = (
            self.context.settings_history.entries(self._serial)
            if self._serial
            else []
        )
        self.history_table.setRowCount(0)
        for entry in reversed(entries[-100:]):
            row = self.history_table.rowCount()
            self.history_table.insertRow(row)
            time_text = entry.updated_at.split("T", 1)[-1] if "T" in entry.updated_at else entry.updated_at
            values = [time_text, entry.table, entry.key, entry.value]
            for column, value in enumerate(values):
                self.history_table.setItem(row, column, QTableWidgetItem(value))

    def _update_controls(self) -> None:
        connected = bool(self._serial)
        enabled_widgets = (
            self.refresh_button,
            self.font_scale,
            self.apply_font,
            self.reset_font,
            *self.animation_spins.values(),
            *self.animation_reset_buttons,
            self.apply_animation,
            self.reset_animation,
            self.timeout_spin,
            self.apply_timeout,
            self.immersive_check,
            self.apply_immersive,
            *self.icon_checks.values(),
            self.apply_icons,
            self.all_icons_button,
            self.clear_icons_button,
            self.hidden_table,
            self.hidden_key,
            self.hidden_value,
            self.read_hidden,
            self.write_hidden,
        )
        for widget in enabled_widgets:
            widget.setEnabled(connected)
        self._update_hidden_buttons()

    def _update_hidden_buttons(self) -> None:
        connected = bool(self._serial)
        self.read_hidden.setEnabled(connected)
        self.write_hidden.setEnabled(connected)
