from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...infrastructure.parsers import DeviceInfo, parse_battery
from ...services.battery import (
    BATTERY_HEALTH,
    BATTERY_STATUS,
    BatterySample,
    BatterySampler,
    BatteryService,
    export_csv,
)
from ...services.danger import get_danger
from ..page import BasePage
from ..widgets.danger_dialog import confirm_danger


MAX_SAMPLES = 50000


class BatteryPage(BasePage):
    def __init__(self, context) -> None:
        super().__init__(context)
        self.service = BatteryService(context.adb, context.battery_tracker)
        self.sampler = BatterySampler(context.adb)
        self._serial = ""
        self._info_process = None
        self._action_process = None
        self._samples: list[BatterySample] = []
        self._last_info = None

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
        heading = QLabel("电池与电源")
        heading.setObjectName("SectionTitle")
        self.message_label = QLabel("选择设备后读取电池信息。")
        self.message_label.setObjectName("Muted")
        self.refresh_button = QPushButton("刷新电池")
        header.addWidget(heading)
        header.addSpacing(12)
        header.addWidget(self.message_label, 1)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        layout.addWidget(self._build_info_group())
        layout.addWidget(self._build_simulation_group())
        layout.addWidget(self._build_sample_group())
        layout.addStretch(1)

        self.refresh_button.clicked.connect(self._refresh_info)
        self.apply_level.clicked.connect(self._apply_level)
        self.apply_temperature.clicked.connect(self._apply_temperature)
        self.apply_status.clicked.connect(self._apply_status)
        self.apply_charging.clicked.connect(self._apply_charging)
        self.unplug_button.clicked.connect(self._unplug)
        self.reset_button.clicked.connect(self._reset)
        self.start_sample.clicked.connect(self._start_sampling)
        self.stop_sample.clicked.connect(self._stop_sampling)
        self.export_button.clicked.connect(self._export)
        self.level_slider.valueChanged.connect(self.level_spin.setValue)
        self.level_spin.valueChanged.connect(self.level_slider.setValue)
        self.sampler.sample.connect(self._on_sample)
        self.sampler.error.connect(self._on_sample_error)
        self.sampler.state.connect(self._on_sampler_state)

        self._update_controls()

    def _build_info_group(self) -> QGroupBox:
        group = QGroupBox("电池信息")
        layout = QGridLayout(group)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(4)

        self.level_value = QLabel("—")
        self.level_value.setObjectName("Value")
        self.temperature_value = QLabel("—")
        self.temperature_value.setObjectName("Value")
        self.voltage_value = QLabel("—")
        self.voltage_value.setObjectName("Value")
        self.status_value = QLabel("—")
        self.health_value = QLabel("—")
        self.source_value = QLabel("—")
        self.current_value = QLabel("—")

        self._add_info(layout, 0, 0, "电量", self.level_value)
        self._add_info(layout, 0, 2, "温度", self.temperature_value)
        self._add_info(layout, 0, 4, "电压", self.voltage_value)
        self._add_info(layout, 1, 0, "状态", self.status_value)
        self._add_info(layout, 1, 2, "健康", self.health_value)
        self._add_info(layout, 1, 4, "供电", self.source_value)
        self._add_info(layout, 2, 0, "电流", self.current_value)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(3, 1)
        layout.setColumnStretch(5, 1)

        self.raw_output = QPlainTextEdit()
        self.raw_output.setReadOnly(True)
        self.raw_output.setMaximumHeight(100)
        self.raw_output.setPlaceholderText("读取后显示 dumpsys battery 原始输出")
        layout.addWidget(QLabel("原始输出"), 3, 0)
        layout.addWidget(self.raw_output, 3, 1, 1, 5)
        return group

    @staticmethod
    def _add_info(layout, row, column, label, value) -> None:
        text = QLabel(label)
        text.setObjectName("Muted")
        layout.addWidget(text, row, column)
        layout.addWidget(value, row, column + 1)

    def _build_simulation_group(self) -> QGroupBox:
        group = QGroupBox("模拟电池")
        layout = QGridLayout(group)
        layout.setContentsMargins(0, 8, 0, 4)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(10)

        self.level_spin = QSpinBox()
        self.level_spin.setRange(0, 100)
        self.level_spin.setValue(50)
        self.level_slider = QSlider(Qt.Orientation.Horizontal)
        self.level_slider.setRange(0, 100)
        self.level_slider.setValue(50)
        self.apply_level = QPushButton("应用电量")
        level_row = QHBoxLayout()
        level_row.setContentsMargins(0, 0, 0, 0)
        level_row.addWidget(self.level_spin)
        level_row.addWidget(QLabel("%（上限 100）"))
        layout.addWidget(QLabel("电量"), 0, 0)
        layout.addLayout(level_row, 0, 1)
        layout.addWidget(self.level_slider, 0, 2)
        layout.addWidget(self.apply_level, 0, 3)

        self.temperature_spin = QDoubleSpinBox()
        self.temperature_spin.setRange(0, 100)
        self.temperature_spin.setDecimals(1)
        self.temperature_spin.setValue(30.0)
        self.apply_temperature = QPushButton("应用温度")
        temperature_row = QHBoxLayout()
        temperature_row.setContentsMargins(0, 0, 0, 0)
        temperature_row.addWidget(self.temperature_spin)
        temperature_row.addWidget(QLabel("°C（上限 100）"))
        layout.addWidget(QLabel("温度"), 1, 0)
        layout.addLayout(temperature_row, 1, 1)
        layout.addWidget(self.apply_temperature, 1, 3)

        self.status_combo = QComboBox()
        for value, label in BATTERY_STATUS.items():
            self.status_combo.addItem(label, value)
        self.apply_status = QPushButton("应用状态")
        layout.addWidget(QLabel("状态"), 2, 0)
        layout.addWidget(self.status_combo, 2, 1)
        layout.addWidget(self.apply_status, 2, 3)

        charging_row = QHBoxLayout()
        self.ac_check = QCheckBox("交流电")
        self.usb_check = QCheckBox("USB")
        self.wireless_check = QCheckBox("无线")
        charging_row.addWidget(self.ac_check)
        charging_row.addWidget(self.usb_check)
        charging_row.addWidget(self.wireless_check)
        layout.addWidget(QLabel("供电"), 3, 0)
        layout.addLayout(charging_row, 3, 1, 1, 2)
        self.apply_charging = QPushButton("应用供电")
        layout.addWidget(self.apply_charging, 3, 3)

        action_row = QHBoxLayout()
        self.unplug_button = QPushButton("拔出充电器")
        self.reset_button = QPushButton("恢复真实电池")
        action_row.addWidget(self.unplug_button)
        action_row.addWidget(self.reset_button)
        action_row.addStretch(1)
        layout.addLayout(action_row, 4, 0, 1, 4)

        note = QLabel("模拟值可能影响电量显示和充电判断，重启设备后失效。")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note, 5, 0, 1, 4)
        layout.setColumnStretch(2, 1)
        return group

    def _build_sample_group(self) -> QGroupBox:
        group = QGroupBox("定时采样")
        layout = QGridLayout(group)
        layout.setContentsMargins(0, 8, 0, 4)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(10)

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 60)
        self.interval_spin.setValue(1)
        self.start_sample = QPushButton("开始采样")
        self.start_sample.setObjectName("Primary")
        self.stop_sample = QPushButton("停止采样")
        interval_row = QHBoxLayout()
        interval_row.setContentsMargins(0, 0, 0, 0)
        interval_row.addWidget(self.interval_spin)
        interval_row.addWidget(QLabel("秒（上限 60）"))
        layout.addWidget(QLabel("采样间隔"), 0, 0)
        layout.addLayout(interval_row, 0, 1)
        layout.addWidget(self.start_sample, 0, 2)
        layout.addWidget(self.stop_sample, 0, 3)

        self.sample_state = QLabel("未采样")
        self.sample_state.setObjectName("Muted")
        self.latest_sample = QLabel("最新样本：—")
        self.latest_sample.setObjectName("Muted")
        self.export_button = QPushButton("导出 CSV")
        layout.addWidget(self.sample_state, 1, 0, 1, 2)
        layout.addWidget(self.latest_sample, 1, 2)
        layout.addWidget(self.export_button, 1, 3)
        layout.setColumnStretch(2, 1)
        return group

    def on_activated(self) -> None:
        if self._serial and self._last_info is None:
            self._refresh_info()
        self._update_controls()

    def on_device_changed(self, device: DeviceInfo | None) -> None:
        serial = device.serial if device and device.connected else ""
        if serial == self._serial:
            return
        self._serial = serial
        self._cancel_processes()
        self.sampler.stop()
        self._last_info = None
        self._samples = []
        self._clear_display()
        if serial:
            self.message_label.setText(f"当前设备：{serial}")
            self._refresh_info()
        else:
            self.message_label.setText("未选择设备。")
        self._update_controls()

    def on_deactivated(self) -> None:
        self._cancel_processes()
        if self.sampler.is_running:
            self.sampler.stop()

    def shutdown(self) -> None:
        self._cancel_processes()
        self.sampler.stop()

    def _cancel_processes(self) -> None:
        for process in (self._info_process, self._action_process):
            if process is not None and process.is_running:
                process.cancel()
        self._info_process = None
        self._action_process = None

    def _clear_display(self) -> None:
        for label in (
            self.level_value,
            self.temperature_value,
            self.voltage_value,
            self.status_value,
            self.health_value,
            self.source_value,
            self.current_value,
        ):
            label.setText("—")
        self.raw_output.clear()
        self.sample_state.setText("未采样")
        self.latest_sample.setText("最新样本：—")
        self._update_sample_buttons()

    def _refresh_info(self) -> None:
        if not self._serial:
            self.context.status.error("请先连接设备")
            return
        if self._info_process is not None and self._info_process.is_running:
            return
        serial = self._serial
        self.message_label.setText("正在读取电池信息…")
        process = self.service.info(serial)
        self._info_process = process
        process.finished.connect(
            lambda result, s=serial: self._on_info_finished(s, result)
        )

    def _on_info_finished(self, serial: str, result) -> None:
        if serial != self._serial:
            return
        self._info_process = None
        if not result.ok:
            self.message_label.setText(
                f"读取电池失败：{(result.stderr or result.stdout).strip()}"
            )
            self.context.status.error("读取电池信息失败")
            return
        info = parse_battery(result.stdout)
        self._last_info = info
        self.level_value.setText("—" if info.level is None else f"{info.level}%")
        self.temperature_value.setText(
            "—" if info.temperature_c is None else f"{info.temperature_c:.1f} °C"
        )
        self.voltage_value.setText(
            "—" if info.voltage_mv is None else f"{info.voltage_mv} mV"
        )
        self.status_value.setText(BATTERY_STATUS.get(info.status, "未知"))
        self.health_value.setText(BATTERY_HEALTH.get(info.health, "未知"))
        sources = []
        if info.ac:
            sources.append("交流电")
        if info.usb:
            sources.append("USB")
        if info.wireless:
            sources.append("无线")
        self.source_value.setText("、".join(sources) if sources else "未接电源")
        current = info.raw.get("current now")
        self.current_value.setText(f"{current} µA" if current else "—")
        self.raw_output.setPlainText(result.stdout)
        self.message_label.setText(f"当前设备：{serial}")
        self.context.status.success("电池信息已读取")

    def _confirm(self, spec) -> bool:
        return confirm_danger(self, spec)

    def _apply_level(self) -> None:
        if not self._serial:
            return
        level = self.level_spin.value()
        command = f"dumpsys battery set level {level}"
        spec = get_danger(
            "battery.simulate",
            command=command,
            detail=f"设备电量将显示为 {level}%。重启后失效。",
        )
        if not self._confirm(spec):
            return
        self._track(self.service.set_level(self._serial, level), "电量")

    def _apply_temperature(self) -> None:
        if not self._serial:
            return
        temperature = self.temperature_spin.value()
        tenths = int(round(temperature * 10))
        command = f"dumpsys battery set temp {tenths}"
        spec = get_danger(
            "battery.simulate",
            command=command,
            detail=f"设备电池温度将显示为 {temperature:.1f} °C。重启后失效。",
        )
        if not self._confirm(spec):
            return
        self._track(
            self.service.set_temperature(self._serial, temperature),
            "温度",
        )

    def _apply_status(self) -> None:
        if not self._serial:
            return
        status = self.status_combo.currentData()
        command = f"dumpsys battery set status {status}"
        spec = get_danger(
            "battery.simulate",
            command=command,
            detail=f"设备电池状态将显示为「{self.status_combo.currentText()}」。重启后失效。",
        )
        if not self._confirm(spec):
            return
        self._track(self.service.set_status(self._serial, status), "电池状态")

    def _apply_charging(self) -> None:
        if not self._serial:
            return
        ac = self.ac_check.isChecked()
        usb = self.usb_check.isChecked()
        wireless = self.wireless_check.isChecked()
        command = "; ".join(
            [
                f"dumpsys battery set ac {1 if ac else 0}",
                f"dumpsys battery set usb {1 if usb else 0}",
                f"dumpsys battery set wireless {1 if wireless else 0}",
            ]
        )
        spec = get_danger(
            "battery.simulate",
            command=command,
            detail="按勾选状态模拟交流电、USB 与无线充电来源。重启后失效。",
        )
        if not self._confirm(spec):
            return
        self._track(
            self.service.set_charging_states(
                self._serial, ac, usb, wireless
            ),
            "供电状态",
        )

    def _unplug(self) -> None:
        if not self._serial:
            return
        spec = get_danger(
            "battery.simulate",
            command="dumpsys battery unplug",
            detail="设备将显示为未接充电器。重启后失效。",
        )
        if not self._confirm(spec):
            return
        self._track(self.service.unplug(self._serial), "拔出充电器")

    def _reset(self) -> None:
        if not self._serial:
            return
        spec = get_danger(
            "battery.simulate",
            command="dumpsys battery reset",
            detail="清除所有电池模拟值，恢复设备真实电池状态。",
        )
        if not self._confirm(spec):
            return
        self._track(self.service.reset(self._serial), "恢复真实电池")

    def _track(self, process, label: str) -> None:
        serial = self._serial
        self._action_process = process
        self.message_label.setText(f"正在应用{label}…")
        process.finished.connect(
            lambda result, s=serial, name=label: self._on_action_finished(
                s, name, result
            )
        )
        self._update_controls()

    def _on_action_finished(self, serial: str, label: str, result) -> None:
        self._action_process = None
        if serial != self._serial:
            return
        if result.cancelled:
            self.message_label.setText(f"{label}已取消")
            self._update_controls()
            return
        if not result.ok:
            detail = (result.stderr or result.stdout).strip() or "未知错误"
            self.message_label.setText(f"{label}失败：{detail}")
            self.context.status.error(f"{label}失败：{detail}")
            self._update_controls()
            return
        self.message_label.setText(f"{label}已应用")
        self.context.status.success(f"{label}已应用")
        self._refresh_info()
        self._update_controls()

    def _start_sampling(self) -> None:
        if not self._serial:
            return
        self._samples = []
        self.sample_state.setText("采样中：0 条")
        self.latest_sample.setText("最新样本：—")
        self.sampler.start(self._serial, self.interval_spin.value() * 1000)
        self._update_controls()

    def _stop_sampling(self) -> None:
        self.sampler.stop()
        self.sample_state.setText(f"已停止：{len(self._samples)} 条")
        self._update_controls()

    def _on_sample(self, sample: BatterySample) -> None:
        if len(self._samples) >= MAX_SAMPLES:
            self.sampler.stop()
            self.context.status.error("样本已达到 50000 条，采样已停止")
            self.sample_state.setText("已达到样本上限")
            self._update_controls()
            return
        self._samples.append(sample)
        level = "—" if sample.level is None else f"{sample.level}%"
        temperature = (
            "—" if sample.temperature_c is None else f"{sample.temperature_c:.1f} °C"
        )
        self.sample_state.setText(f"采样中：{len(self._samples)} 条")
        self.latest_sample.setText(f"最新样本：{level} / {temperature} / {sample.status}")
        self._update_sample_buttons()

    def _on_sample_error(self, message: str) -> None:
        self.context.status.error(f"电池采样失败：{message}")
        self.sample_state.setText("采样失败")

    def _on_sampler_state(self, state: str) -> None:
        if state == "采样中":
            self.sample_state.setText(f"采样中：{len(self._samples)} 条")
        elif not self._samples:
            self.sample_state.setText("未采样")
        self._update_controls()

    def _export(self) -> None:
        if not self._samples:
            self.context.status.error("当前没有可导出的采样")
            return
        default_name = (
            f"battery-{self._serial}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv"
        )
        path, _filter = QFileDialog.getSaveFileName(
            self,
            "导出电池采样",
            str(self.context.config.save_root / default_name),
            "CSV (*.csv);;所有文件 (*)",
        )
        if not path:
            return
        try:
            export_csv(path, self._samples)
        except OSError as exc:
            self.context.status.error(f"导出失败：{exc}")
            return
        self.context.status.success(f"已导出 {len(self._samples)} 条样本到 {path}")

    def _update_controls(self) -> None:
        connected = bool(self._serial)
        for widget in (
            self.refresh_button,
            self.level_spin,
            self.level_slider,
            self.apply_level,
            self.temperature_spin,
            self.apply_temperature,
            self.status_combo,
            self.apply_status,
            self.ac_check,
            self.usb_check,
            self.wireless_check,
            self.apply_charging,
            self.unplug_button,
            self.reset_button,
            self.interval_spin,
            self.start_sample,
        ):
            widget.setEnabled(connected)
        self.start_sample.setEnabled(connected and not self.sampler.is_running)
        self.stop_sample.setEnabled(self.sampler.is_running)
        self._update_sample_buttons()

    def _update_sample_buttons(self) -> None:
        self.export_button.setEnabled(bool(self._samples))
