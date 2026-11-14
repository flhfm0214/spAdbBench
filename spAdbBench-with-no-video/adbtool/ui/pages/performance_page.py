from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...infrastructure.parsers import DeviceInfo
from ...services.metrics import MetricsSample
from ..page import BasePage
from ..widgets.foreground_bar import ForegroundAppBar
from ..widgets.metrics_panel import (
    format_frequency,
    format_gb,
    format_temperature,
    format_uptime,
    format_voltage,
)


def format_interval(interval_ms: int) -> str:
    if interval_ms <= 0:
        return "自动刷新已禁用"
    return f"每 {interval_ms / 1000:g} 秒"


class PerformancePage(BasePage):
    def __init__(self, context) -> None:
        super().__init__(context)
        self.monitor = context.metrics
        self._serial = ""
        self._last_sample: MetricsSample | None = None
        self._error = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(10)

        header = QHBoxLayout()
        heading = QLabel("性能监控")
        heading.setObjectName("SectionTitle")
        self.message_label = QLabel("连接设备后按设定间隔读取 CPU、内存、电池与 GPU。")
        self.message_label.setObjectName("Muted")
        self.state_label = QLabel("未连接设备")
        self.state_label.setObjectName("Muted")
        header.addWidget(heading)
        header.addSpacing(12)
        header.addWidget(self.message_label, 1)
        header.addWidget(self.state_label)
        layout.addLayout(header)

        self.foreground_bar = ForegroundAppBar(context)
        layout.addWidget(self.foreground_bar)

        controls = QHBoxLayout()
        interval_label = QLabel("采样间隔")
        interval_label.setObjectName("Muted")
        self.interval_combo = QDoubleSpinBox()
        self.interval_combo.setRange(0.0, 60.0)
        self.interval_combo.setDecimals(1)
        self.interval_combo.setSingleStep(0.1)
        self.interval_combo.setSpecialValueText("禁用")
        self.interval_combo.setToolTip("0.1–60 秒；填 0 禁用自动刷新，仍可立即采样")
        self._select_interval(context.config.metrics_interval_ms)
        self.refresh_button = QPushButton("立即采样")
        self.refresh_button.setToolTip("立即执行一次性能采样")
        self.copy_button = QPushButton("复制快照")
        self.copy_button.setToolTip("把当前性能数据复制为文本")
        controls.addWidget(interval_label)
        controls.addWidget(self.interval_combo)
        controls.addWidget(QLabel("秒（上限 60，0 为禁用）"))
        controls.addWidget(self.refresh_button)
        controls.addWidget(self.copy_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        summary = QHBoxLayout()
        summary.setSpacing(10)
        cpu_card, self.cpu_value, self.cpu_detail, self.cpu_bar = self._stat_card(
            "CPU 使用率", bar=True
        )
        memory_card, self.memory_value, self.memory_detail, self.memory_bar = (
            self._stat_card("内存占用", bar=True)
        )
        battery_card, self.battery_value, self.battery_detail, _ = self._stat_card(
            "电池电量"
        )
        load_card, self.load_value, self.load_detail, _ = self._stat_card("系统负载")
        for card in (cpu_card, memory_card, battery_card, load_card):
            summary.addWidget(card, 1)
        layout.addLayout(summary)

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(self._build_cpu_group(), 3)
        body.addWidget(self._build_detail_group(), 2)
        layout.addLayout(body, 1)

        self.interval_combo.valueChanged.connect(self._on_interval_changed)
        self.refresh_button.clicked.connect(self._refresh)
        self.copy_button.clicked.connect(self._copy_snapshot)
        self.monitor.sample_ready.connect(self.render_sample)
        self.monitor.sample_failed.connect(self._on_failure)
        context.metrics_interval_changed.connect(self._on_global_interval)
        self._update_controls()

    def _select_interval(self, interval_ms: int) -> None:
        self.interval_combo.blockSignals(True)
        self.interval_combo.setValue(max(0, interval_ms) / 1000)
        self.interval_combo.blockSignals(False)

    def _on_global_interval(self, interval_ms: int) -> None:
        self._select_interval(interval_ms)
        if self._last_sample is not None:
            self._set_state_success(self._last_sample)

    def _stat_card(self, title: str, bar: bool = False):
        card = QGroupBox(title)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(4)
        value = QLabel("—")
        value.setObjectName("MetricValue")
        detail = QLabel("—")
        detail.setObjectName("MetricDetail")
        detail.setWordWrap(True)
        progress = None
        layout.addWidget(value)
        if bar:
            progress = QProgressBar()
            progress.setRange(0, 100)
            progress.setTextVisible(False)
            progress.setFixedHeight(8)
            layout.addWidget(progress)
        layout.addWidget(detail)
        return card, value, detail, progress

    def _build_cpu_group(self) -> QGroupBox:
        group = QGroupBox("CPU 核心")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(4)

        self.cpu_table = QTableWidget(0, 3)
        self.cpu_table.setHorizontalHeaderLabels(["核心", "当前频率", "占用"])
        self.cpu_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.cpu_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.cpu_table.setAlternatingRowColors(True)
        self.cpu_table.verticalHeader().setVisible(False)
        header = self.cpu_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.cpu_table, 1)

        hint = QLabel("首次采样显示“采样中”，下一次开始显示百分比。")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return group

    def _build_detail_group(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        memory_group = QGroupBox("内存")
        memory_grid = QGridLayout(memory_group)
        memory_grid.setContentsMargins(0, 4, 0, 0)
        memory_grid.setHorizontalSpacing(10)
        memory_grid.setVerticalSpacing(4)
        self.memory_used_value = self._detail_value("—")
        self.memory_available_value = self._detail_value("—")
        self.swap_value = self._detail_value("—")
        self.uptime_value = self._detail_value("—")
        self._add_detail_row(memory_grid, 0, "已用", self.memory_used_value)
        self._add_detail_row(memory_grid, 1, "可用", self.memory_available_value)
        self._add_detail_row(memory_grid, 2, "交换分区", self.swap_value)
        self._add_detail_row(memory_grid, 3, "运行时间", self.uptime_value)
        layout.addWidget(memory_group)

        battery_group = QGroupBox("电池")
        battery_grid = QGridLayout(battery_group)
        battery_grid.setContentsMargins(0, 4, 0, 0)
        battery_grid.setHorizontalSpacing(10)
        battery_grid.setVerticalSpacing(4)
        self.battery_health_value = self._detail_value("—")
        self.battery_temp_value = self._detail_value("—")
        self.battery_voltage_value = self._detail_value("—")
        self.battery_power_value = self._detail_value("—")
        self._add_detail_row(battery_grid, 0, "健康", self.battery_health_value)
        self._add_detail_row(battery_grid, 1, "温度", self.battery_temp_value)
        self._add_detail_row(battery_grid, 2, "电压", self.battery_voltage_value)
        self._add_detail_row(battery_grid, 3, "供电", self.battery_power_value)
        layout.addWidget(battery_group)

        gpu_group = QGroupBox("图形与设备")
        gpu_grid = QGridLayout(gpu_group)
        gpu_grid.setContentsMargins(0, 4, 0, 0)
        gpu_grid.setHorizontalSpacing(10)
        gpu_grid.setVerticalSpacing(4)
        self.gpu_value = QLabel("—")
        self.gpu_value.setObjectName("Value")
        self.gpu_value.setWordWrap(True)
        self.gpu_value.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.gpu_detail = QLabel("—")
        self.gpu_detail.setObjectName("Muted")
        self.gpu_detail.setWordWrap(True)
        self.gles_value = self._detail_value("—")
        self.platform_value = self._detail_value("—")
        self.model_value = self._detail_value("—")
        self._add_detail_row(gpu_grid, 0, "渲染器", self.gpu_value)
        self._add_detail_row(gpu_grid, 1, "版本", self.gles_value)
        self._add_detail_row(gpu_grid, 2, "平台", self.platform_value)
        self._add_detail_row(gpu_grid, 3, "型号", self.model_value)
        gpu_grid.addWidget(self.gpu_detail, 4, 0, 1, 2)
        layout.addWidget(gpu_group)
        layout.addStretch(1)
        return panel

    @staticmethod
    def _detail_value(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("Value")
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    @staticmethod
    def _add_detail_row(grid: QGridLayout, row: int, label: str, value: QLabel) -> None:
        name = QLabel(label)
        name.setObjectName("Muted")
        grid.addWidget(name, row, 0)
        grid.addWidget(value, row, 1)
        grid.setColumnStretch(1, 1)

    def on_activated(self) -> None:
        if not self._serial:
            return
        sample = self.monitor.last_sample
        if sample is not None and sample.serial == self._serial:
            self.render_sample(sample)
        self._set_state("正在采样…")
        self.monitor.refresh()
        self.foreground_bar.refresh()

    def on_device_changed(self, device: DeviceInfo | None) -> None:
        serial = device.serial if device and device.connected else ""
        changed = serial != self._serial
        self._serial = serial
        self.foreground_bar.set_serial(serial)
        if changed:
            self._clear_stats()
        if not serial:
            self.message_label.setText("未选择设备。")
            self._set_state("未连接设备")
            self._update_controls()
            return
        self.message_label.setText(f"当前设备：{serial}")
        self._set_state("正在采样…")
        self._update_controls()
        if changed:
            self.monitor.refresh()
            self.foreground_bar.refresh()

    def _update_controls(self) -> None:
        ready = bool(self._serial)
        self.interval_combo.setEnabled(ready)
        self.refresh_button.setEnabled(ready)
        self.copy_button.setEnabled(ready and self._last_sample is not None)

    def _refresh(self) -> None:
        if not self._serial:
            return
        self._set_state("正在采样…")
        self.monitor.refresh()

    def _on_interval_changed(self, seconds: float) -> None:
        interval_ms = round(seconds * 1000)
        self.context.set_metrics_interval(interval_ms)
        self.context.status.info(
            "性能自动刷新已禁用"
            if interval_ms <= 0
            else f"性能采样间隔已设为 {seconds:g} 秒"
        )
        if self._last_sample is not None:
            self._set_state_success(self._last_sample)

    def render_sample(self, sample: MetricsSample) -> None:
        if sample.serial != self._serial:
            return
        self._last_sample = sample
        self._error = ""
        self.cpu_value.setText(
            f"{sample.cpu_usage}%" if sample.cpu_usage is not None else "采样中"
        )
        self.cpu_bar.setValue(sample.cpu_usage or 0)
        self.cpu_detail.setText(
            f"{len(sample.cores)} 核 · 平均 {format_frequency(sample.average_frequency_mhz)}"
        )

        percent = sample.memory_percent
        self.memory_value.setText(f"{percent}%" if percent is not None else "—")
        self.memory_bar.setValue(percent or 0)
        self.memory_detail.setText(
            f"{format_gb(sample.memory_used_kb)} / {format_gb(sample.memory_total_kb)}"
        )
        self.memory_used_value.setText(format_gb(sample.memory_used_kb))
        self.memory_available_value.setText(format_gb(sample.memory_available_kb))
        swap_used = max(0, sample.swap_total_kb - sample.swap_free_kb)
        self.swap_value.setText(
            f"{format_gb(swap_used)} / {format_gb(sample.swap_total_kb)}"
            if sample.swap_total_kb
            else "未启用"
        )
        self.uptime_value.setText(format_uptime(sample.uptime_seconds))

        self.battery_value.setText(
            f"{sample.battery_level}%" if sample.battery_level is not None else "—"
        )
        battery_parts = [sample.battery_status]
        if sample.battery_temperature_c is not None:
            battery_parts.append(format_temperature(sample.battery_temperature_c))
        self.battery_detail.setText(" · ".join(part for part in battery_parts if part))
        self.battery_health_value.setText(sample.battery_health)
        self.battery_temp_value.setText(format_temperature(sample.battery_temperature_c))
        self.battery_voltage_value.setText(format_voltage(sample.battery_voltage_mv))
        self.battery_power_value.setText(sample.battery_power)

        self.load_value.setText(
            f"{sample.load_1:.2f}" if sample.load_1 is not None else "—"
        )
        self.load_detail.setText(
            f"5 分钟 {sample.load_5:.2f} · 15 分钟 {sample.load_15:.2f}"
            if sample.load_5 is not None and sample.load_15 is not None
            else f"运行 {format_uptime(sample.uptime_seconds)}"
        )

        self.gpu_value.setText(sample.gpu_renderer or "—")
        self.gpu_value.setToolTip(sample.gpu_renderer)
        gpu_parts = [part for part in (sample.gpu_vendor, sample.gles_version) if part]
        self.gpu_detail.setText(" · ".join(gpu_parts) or "—")
        self.gles_value.setText(sample.gles_version or "—")
        self.platform_value.setText(sample.platform or "—")
        self.model_value.setText(sample.model or "—")

        self._render_cores(sample)
        self._set_state_success(sample)
        self._update_controls()

    def _render_cores(self, sample: MetricsSample) -> None:
        self.cpu_table.setRowCount(0)
        rows = [("整体", format_frequency(sample.average_frequency_mhz), sample.cpu_usage)]
        rows.extend(
            (
                f"核心 {core.index}",
                f"{core.frequency_mhz} MHz" if core.frequency_mhz else "—",
                core.usage_percent,
            )
            for core in sample.cores
        )
        for row, (name, frequency, usage) in enumerate(rows):
            self.cpu_table.insertRow(row)
            self.cpu_table.setItem(row, 0, QTableWidgetItem(name))
            self.cpu_table.setItem(row, 1, QTableWidgetItem(frequency))
            self.cpu_table.setItem(
                row,
                2,
                QTableWidgetItem(f"{usage}%" if usage is not None else "采样中"),
            )

    def _set_state_success(self, sample: MetricsSample) -> None:
        self._set_state(
            f"更新于 {sample.captured_at.strftime('%H:%M:%S')} · "
            f"{format_interval(self.monitor.interval_ms)}"
        )

    def _set_state(self, text: str, error: bool = False) -> None:
        self.state_label.setObjectName("MetricError" if error else "Muted")
        self.state_label.setText(text)
        self.state_label.style().unpolish(self.state_label)
        self.state_label.style().polish(self.state_label)

    def _on_failure(self, message: str) -> None:
        if not self._serial:
            return
        self._error = message
        self._set_state(f"采样失败：{message}", error=True)

    def _clear_stats(self) -> None:
        self._last_sample = None
        self.cpu_value.setText("—")
        self.cpu_detail.setText("—")
        self.cpu_bar.setValue(0)
        self.memory_value.setText("—")
        self.memory_detail.setText("—")
        self.memory_bar.setValue(0)
        self.memory_used_value.setText("—")
        self.memory_available_value.setText("—")
        self.swap_value.setText("—")
        self.uptime_value.setText("—")
        self.battery_value.setText("—")
        self.battery_detail.setText("—")
        self.battery_health_value.setText("—")
        self.battery_temp_value.setText("—")
        self.battery_voltage_value.setText("—")
        self.battery_power_value.setText("—")
        self.load_value.setText("—")
        self.load_detail.setText("—")
        self.gpu_value.setText("—")
        self.gpu_value.setToolTip("")
        self.gpu_detail.setText("—")
        self.gles_value.setText("—")
        self.platform_value.setText("—")
        self.model_value.setText("—")
        self.cpu_table.setRowCount(0)
        self._update_controls()

    def _copy_snapshot(self) -> None:
        sample = self._last_sample
        if sample is None:
            self.context.status.error("尚无可复制的性能数据")
            return
        lines = [
            f"设备：{sample.serial}",
            f"采样时间：{sample.captured_at.strftime('%Y-%m-%d %H:%M:%S')}",
            f"CPU：{sample.cpu_usage}% / {len(sample.cores)} 核 / "
            f"平均 {format_frequency(sample.average_frequency_mhz)}",
            f"内存：{sample.memory_percent}% / "
            f"{format_gb(sample.memory_used_kb)} 已用 / "
            f"{format_gb(sample.memory_total_kb)} 总计",
            f"电池：{sample.battery_level}% / {sample.battery_status} / "
            f"{format_temperature(sample.battery_temperature_c)} / "
            f"{format_voltage(sample.battery_voltage_mv)}",
            f"负载：{sample.load_1} / {sample.load_5} / {sample.load_15}",
            f"运行时间：{format_uptime(sample.uptime_seconds)}",
            f"GPU：{sample.gpu_renderer or '—'} / {sample.gles_version or '—'}",
            f"平台：{sample.platform or '—'} / 型号：{sample.model or '—'}",
        ]
        QApplication.clipboard().setText("\n".join(lines))
        self.context.status.success("性能快照已复制")

    def shutdown(self) -> None:
        self.foreground_bar.shutdown()
