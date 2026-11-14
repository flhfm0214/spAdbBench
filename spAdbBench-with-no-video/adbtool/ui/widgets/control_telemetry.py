from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...services.metrics import MetricsSample
from .metrics_panel import format_frequency, format_gb, format_temperature


class _MetricCell(QWidget):
    def __init__(
        self,
        label: str,
        *,
        bar: bool = False,
        detail: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        name_label = QLabel(label)
        name_label.setObjectName("Muted")
        self.value = QLabel("—")
        self.value.setObjectName("SidebarValue")
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight)
        row.addWidget(name_label)
        row.addStretch(1)
        row.addWidget(self.value)
        layout.addLayout(row)

        self.bar: QProgressBar | None = None
        if bar:
            self.bar = QProgressBar()
            self.bar.setRange(0, 100)
            self.bar.setTextVisible(False)
            self.bar.setFixedHeight(6)
            layout.addWidget(self.bar)

        self.detail: QLabel | None = None
        if detail:
            self.detail = QLabel("—")
            self.detail.setObjectName("MetricDetail")
            layout.addWidget(self.detail)


class ControlTelemetry(QWidget):
    """Live device metrics; reflows beside or above the video on rotation."""

    layout_changed = Signal()

    def __init__(self, monitor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.monitor = monitor
        self._compact = False
        self._last_sample: MetricsSample | None = None
        self.setObjectName("ControlTelemetry")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(4)

        title = QLabel("设备状态")
        title.setObjectName("SidebarTitle")
        self.updated = QLabel("等待采样")
        self.updated.setObjectName("SidebarHint")
        self.updated.setAlignment(Qt.AlignmentFlag.AlignRight)
        header = QHBoxLayout()
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.updated)
        layout.addLayout(header)
        layout.addWidget(_separator())

        self.metrics_host = QWidget()
        self.metrics_layout = QGridLayout(self.metrics_host)
        self.metrics_layout.setContentsMargins(0, 0, 0, 0)
        self.metrics_layout.setHorizontalSpacing(14)
        self.metrics_layout.setVerticalSpacing(4)
        layout.addWidget(self.metrics_host)

        self.cpu_cell = _MetricCell("CPU 占用", bar=True)
        self.memory_cell = _MetricCell("内存占用", bar=True, detail=True)
        self.cpu_frequency_cell = _MetricCell("CPU 频率")
        self.gpu_frequency_cell = _MetricCell("GPU 频率")
        self.cpu_temperature_cell = _MetricCell("CPU 温度")
        self.gpu_temperature_cell = _MetricCell("GPU 温度")
        self.battery_temperature_cell = _MetricCell("电池温度")
        self._cells = (
            self.cpu_cell,
            self.memory_cell,
            self.cpu_frequency_cell,
            self.gpu_frequency_cell,
            self.cpu_temperature_cell,
            self.gpu_temperature_cell,
            self.battery_temperature_cell,
        )
        self.cpu_value = self.cpu_cell.value
        self.cpu_bar = self.cpu_cell.bar
        self.memory_value = self.memory_cell.value
        self.memory_bar = self.memory_cell.bar
        self.memory_detail = self.memory_cell.detail
        self.cpu_frequency_value = self.cpu_frequency_cell.value
        self.gpu_frequency_value = self.gpu_frequency_cell.value
        self.cpu_temperature_value = self.cpu_temperature_cell.value
        self.gpu_temperature_value = self.gpu_temperature_cell.value
        self.battery_temperature_value = self.battery_temperature_cell.value

        layout.addWidget(_separator())
        self.sensor_title = QLabel("传感器温度")
        self.sensor_title.setObjectName("SidebarTitle")
        self.sensor_detail = QLabel("—")
        self.sensor_detail.setObjectName("SidebarSensor")
        self.sensor_detail.setWordWrap(True)
        layout.addWidget(self.sensor_title)
        layout.addWidget(self.sensor_detail)

        self.error_label = QLabel("")
        self.error_label.setObjectName("MetricError")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)

        self.monitor.sample_ready.connect(self.update_sample)
        self.monitor.sample_failed.connect(self._on_failure)
        self._rebuild_metrics()
        self.clear()

    def set_compact(self, compact: bool) -> None:
        if self._compact == compact:
            return
        self._compact = compact
        self._rebuild_metrics()
        self._render_sensors()

    def _rebuild_metrics(self) -> None:
        while self.metrics_layout.count():
            item = self.metrics_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(self.metrics_host)
        columns = 4 if self._compact else 1
        for index, cell in enumerate(self._cells):
            self.metrics_layout.addWidget(
                cell,
                index // columns,
                index % columns,
            )
        for column in range(4):
            self.metrics_layout.setColumnStretch(
                column,
                1 if column < columns else 0,
            )

    def clear(self) -> None:
        for value in (
            self.cpu_value,
            self.memory_value,
            self.cpu_frequency_value,
            self.gpu_frequency_value,
            self.cpu_temperature_value,
            self.gpu_temperature_value,
            self.battery_temperature_value,
        ):
            value.setText("—")
        self.cpu_bar.setValue(0)
        self.memory_bar.setValue(0)
        self.memory_detail.setText("—")
        self.sensor_detail.setText("—")
        self.error_label.clear()
        self.error_label.hide()
        self.updated.setText("等待采样")

    def set_waiting(self) -> None:
        self._last_sample = None
        self.clear()
        self.updated.setText("连接中…")

    def update_sample(self, sample: MetricsSample) -> None:
        self._last_sample = sample
        self.cpu_value.setText(
            f"{sample.cpu_usage}%" if sample.cpu_usage is not None else "采样中"
        )
        self.cpu_bar.setValue(sample.cpu_usage or 0)

        percent = sample.memory_percent
        self.memory_value.setText(f"{percent}%" if percent is not None else "—")
        self.memory_bar.setValue(percent or 0)
        memory_text = (
            f"{format_gb(sample.memory_used_kb)} / {format_gb(sample.memory_total_kb)}"
        )
        self.memory_value.setToolTip(memory_text)
        self.memory_detail.setText(memory_text)

        self.cpu_frequency_value.setText(format_frequency(sample.average_frequency_mhz))
        self.cpu_frequency_value.setToolTip(
            f"最高 {format_frequency(sample.max_frequency_mhz)}"
        )
        self.gpu_frequency_value.setText(format_frequency(sample.gpu_frequency_mhz))
        self.cpu_temperature_value.setText(format_temperature(sample.cpu_temperature_c))
        self.gpu_temperature_value.setText(format_temperature(sample.gpu_temperature_c))
        self.battery_temperature_value.setText(
            format_temperature(sample.battery_temperature_c)
        )
        self._render_sensors()

        self.error_label.clear()
        self.error_label.hide()
        self.updated.setText(sample.captured_at.strftime("%H:%M:%S"))
        self.layout_changed.emit()

    def _render_sensors(self) -> None:
        sample = self._last_sample
        if sample is None:
            self.sensor_detail.setText("—")
            return
        sensors = sample.sensor_temperatures[:10]
        if not sensors:
            self.sensor_detail.setText("—")
            return
        if self._compact:
            text = " · ".join(
                f"{sensor.name} {sensor.celsius:.1f}℃" for sensor in sensors[:6]
            )
            if len(sensors) > 6:
                text += " …"
            self.sensor_detail.setText(text)
        else:
            self.sensor_detail.setText(
                "\n".join(
                    f"{sensor.name}  {sensor.celsius:.1f} ℃" for sensor in sensors
                )
            )

    def _on_failure(self, message: str) -> None:
        self.error_label.setText(f"采样失败：{message}")
        self.error_label.show()
        self.updated.setText("采样失败")


def _separator() -> QFrame:
    line = QFrame()
    line.setObjectName("Separator")
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Plain)
    return line
