from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from ...services.metrics import MetricsSample


def format_gb(kilobytes: int) -> str:
    return f"{kilobytes / 1048576:.1f} GB"


def format_frequency(mhz: int | None) -> str:
    if not mhz:
        return "—"
    if mhz >= 1000:
        return f"{mhz / 1000:.2f} GHz"
    return f"{mhz} MHz"


def format_uptime(seconds: int | None) -> str:
    if seconds is None:
        return "—"
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    if days:
        return f"{days} 天 {hours} 小时"
    if hours:
        return f"{hours} 小时 {minutes} 分"
    return f"{minutes} 分"


def format_temperature(celsius: float | None) -> str:
    return f"{celsius:.1f} ℃" if celsius is not None else "—"


def format_voltage(millivolts: int | None) -> str:
    return f"{millivolts / 1000:.2f} V" if millivolts is not None else "—"


def _separator() -> QFrame:
    line = QFrame()
    line.setObjectName("Separator")
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Plain)
    return line


class MetricsPanel(QWidget):
    def __init__(self, context, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.monitor = context.metrics

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(5)

        cpu_row = QHBoxLayout()
        cpu_label = QLabel("CPU")
        cpu_label.setObjectName("Muted")
        self.cpu_value = QLabel("—")
        self.cpu_value.setObjectName("Value")
        self.cpu_value.setAlignment(Qt.AlignmentFlag.AlignRight)
        cpu_row.addWidget(cpu_label)
        cpu_row.addStretch(1)
        cpu_row.addWidget(self.cpu_value)
        self.cpu_bar = QProgressBar()
        self.cpu_bar.setRange(0, 100)
        self.cpu_bar.setTextVisible(False)
        self.cpu_bar.setFixedHeight(8)
        self.cpu_detail = QLabel("连接设备后开始采样")
        self.cpu_detail.setObjectName("MetricDetail")
        layout.addLayout(cpu_row)
        layout.addWidget(self.cpu_bar)
        layout.addWidget(self.cpu_detail)
        layout.addWidget(_separator())

        memory_row = QHBoxLayout()
        memory_label = QLabel("内存")
        memory_label.setObjectName("Muted")
        self.memory_value = QLabel("—")
        self.memory_value.setObjectName("Value")
        self.memory_value.setAlignment(Qt.AlignmentFlag.AlignRight)
        memory_row.addWidget(memory_label)
        memory_row.addStretch(1)
        memory_row.addWidget(self.memory_value)
        self.memory_bar = QProgressBar()
        self.memory_bar.setRange(0, 100)
        self.memory_bar.setTextVisible(False)
        self.memory_bar.setFixedHeight(8)
        self.memory_detail = QLabel("—")
        self.memory_detail.setObjectName("MetricDetail")
        layout.addLayout(memory_row)
        layout.addWidget(self.memory_bar)
        layout.addWidget(self.memory_detail)
        layout.addWidget(_separator())

        battery_row = QHBoxLayout()
        battery_label = QLabel("电池")
        battery_label.setObjectName("Muted")
        self.battery_value = QLabel("—")
        self.battery_value.setObjectName("Value")
        self.battery_value.setAlignment(Qt.AlignmentFlag.AlignRight)
        battery_row.addWidget(battery_label)
        battery_row.addStretch(1)
        battery_row.addWidget(self.battery_value)
        self.battery_detail = QLabel("—")
        self.battery_detail.setObjectName("MetricDetail")
        layout.addLayout(battery_row)
        layout.addWidget(self.battery_detail)
        layout.addWidget(_separator())

        gpu_label = QLabel("GPU")
        gpu_label.setObjectName("Muted")
        self.gpu_value = QLabel("—")
        self.gpu_value.setObjectName("Value")
        self.gpu_value.setWordWrap(True)
        self.gpu_detail = QLabel("—")
        self.gpu_detail.setObjectName("MetricDetail")
        self.gpu_detail.setWordWrap(True)
        layout.addWidget(gpu_label)
        layout.addWidget(self.gpu_value)
        layout.addWidget(self.gpu_detail)
        layout.addStretch(1)

        self.error_label = QLabel("")
        self.error_label.setObjectName("MetricError")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        self.updated_label = QLabel("等待采样")
        self.updated_label.setObjectName("Muted")
        layout.addWidget(self.error_label)
        layout.addWidget(self.updated_label)

        self.monitor.sample_ready.connect(self.update_sample)
        self.monitor.sample_failed.connect(self._on_failure)

    def clear(self) -> None:
        self.cpu_value.setText("—")
        self.cpu_detail.setText("连接设备后开始采样")
        self.cpu_bar.setValue(0)
        self.memory_value.setText("—")
        self.memory_detail.setText("—")
        self.memory_bar.setValue(0)
        self.battery_value.setText("—")
        self.battery_detail.setText("—")
        self.gpu_value.setText("—")
        self.gpu_detail.setText("—")
        self.updated_label.setText("等待采样")
        self.error_label.clear()
        self.error_label.hide()

    def update_sample(self, sample: MetricsSample) -> None:
        cpu_text = f"{sample.cpu_usage}%" if sample.cpu_usage is not None else "采样中"
        self.cpu_value.setText(cpu_text)
        self.cpu_bar.setValue(sample.cpu_usage or 0)
        frequency = format_frequency(sample.average_frequency_mhz)
        core_count = len(sample.cores)
        self.cpu_detail.setText(f"{core_count} 核 · 平均 {frequency}")

        percent = sample.memory_percent
        self.memory_value.setText(f"{percent}%" if percent is not None else "—")
        self.memory_bar.setValue(percent or 0)
        self.memory_detail.setText(
            f"{format_gb(sample.memory_used_kb)} / {format_gb(sample.memory_total_kb)}"
        )

        self.battery_value.setText(
            f"{sample.battery_level}%" if sample.battery_level is not None else "—"
        )
        battery_parts = [sample.battery_status]
        if sample.battery_temperature_c is not None:
            battery_parts.append(format_temperature(sample.battery_temperature_c))
        self.battery_detail.setText(" · ".join(part for part in battery_parts if part))

        renderer = sample.gpu_renderer or "—"
        self.gpu_value.setText(renderer)
        self.gpu_value.setToolTip(renderer)
        gpu_parts = [part for part in (sample.gpu_vendor, sample.gles_version) if part]
        self.gpu_detail.setText(" · ".join(gpu_parts) or "—")

        self.error_label.clear()
        self.error_label.hide()
        self.updated_label.setText(
            f"更新于 {sample.captured_at.strftime('%H:%M:%S')}"
        )

    def _on_failure(self, message: str) -> None:
        if not self.monitor.serial:
            return
        self.error_label.setText(f"采样失败：{message}")
        self.error_label.show()
        self.updated_label.setText("采样失败")
