from __future__ import annotations

import time

import qrcode
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ...services.wireless import (
    CONNECT_SERVICE,
    PAIRING_SERVICE,
    find_service,
    make_pairing_credentials,
    parse_mdns_services,
)


_QR_SIZE = 300
_PAIR_TIMEOUT_SECONDS = 120


def make_qr_pixmap(payload: str, size: int = _QR_SIZE) -> QPixmap:
    code = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=1,
        border=4,
    )
    code.add_data(payload)
    code.make(fit=True)
    matrix = code.get_matrix()
    modules = len(matrix)
    scale = max(2, size // max(1, modules))
    side = modules * scale
    image = QImage(side, side, QImage.Format.Format_RGB32)
    image.fill(QColor("#ffffff"))
    painter = QPainter(image)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#000000"))
    for row, values in enumerate(matrix):
        for column, filled in enumerate(values):
            if filled:
                painter.drawRect(column * scale, row * scale, scale, scale)
    painter.end()
    return QPixmap.fromImage(image)


class WirelessQrDialog(QDialog):
    """QR-code pairing for Android 11+ wireless debugging."""

    paired = Signal(str)

    def __init__(self, adb, parent=None) -> None:
        super().__init__(parent)
        self.adb = adb
        self.setWindowTitle("无线调试二维码配对")
        self.setMinimumWidth(420)
        self.setModal(True)
        self._name = ""
        self._password = ""
        self._pairing_attempted = ""
        self._pairing_ip = ""
        self._paired = False
        self._expired = False
        self._connect_attempts: set[str] = set()
        self._deadline = 0.0
        self._mdns_process = None
        self._pair_process = None
        self._connect_process = None

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(900)
        self._poll_timer.timeout.connect(self._poll)
        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(self._poll)
        self._close_timer = QTimer(self)
        self._close_timer.setSingleShot(True)
        self._close_timer.timeout.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        heading = QLabel("无线调试二维码配对")
        heading.setObjectName("SectionTitle")
        hint = QLabel("手机：开发者选项 → 无线调试 → 二维码配对，然后扫描。")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(hint)

        self.qr_label = QLabel()
        self.qr_label.setFixedSize(_QR_SIZE, _QR_SIZE)
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setStyleSheet(
            "background: #ffffff; border: 1px solid #d0d7de; border-radius: 6px;"
        )
        layout.addWidget(self.qr_label, 0, Qt.AlignmentFlag.AlignHCenter)

        self.status_label = QLabel("正在生成二维码…")
        self.status_label.setObjectName("Muted")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.address_label = QLabel("")
        self.address_label.setObjectName("Muted")
        self.address_label.setWordWrap(True)
        layout.addWidget(self.address_label)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.regenerate_button = QPushButton("重新生成")
        self.close_button = QPushButton("关闭")
        self.close_button.setObjectName("Primary")
        buttons.addWidget(self.regenerate_button)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

        self.regenerate_button.clicked.connect(self._regenerate)
        self.close_button.clicked.connect(self.accept)
        self._regenerate()

    def _regenerate(self) -> None:
        self._cancel_processes()
        self._retry_timer.stop()
        self._close_timer.stop()
        self._name, self._password, payload = make_pairing_credentials()
        self.qr_label.setPixmap(make_qr_pixmap(payload))
        self._pairing_attempted = ""
        self._pairing_ip = ""
        self._paired = False
        self._expired = False
        self._connect_attempts.clear()
        self._deadline = time.monotonic() + _PAIR_TIMEOUT_SECONDS
        self.address_label.clear()
        self._set_status("等待手机扫描二维码…")
        self._poll_timer.start()
        self._poll()

    def _set_status(self, text: str, error: bool = False) -> None:
        self.status_label.setText(text)
        self.status_label.setObjectName("WarningText" if error else "Muted")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _poll(self) -> None:
        if self._expired:
            return
        if not self._paired and time.monotonic() > self._deadline:
            self._expired = True
            self._poll_timer.stop()
            self._set_status("等待超时，请点「重新生成」后再扫描。", error=True)
            return
        if any(
            process is not None
            for process in (
                self._mdns_process,
                self._pair_process,
                self._connect_process,
            )
        ):
            return
        process = self.adb.run(
            None,
            "mdns",
            "services",
            timeout_ms=4000,
            record=False,
        )
        self._mdns_process = process
        process.finished.connect(
            lambda result, p=process: self._on_mdns(p, result)
        )

    def _on_mdns(self, process, result) -> None:
        if process is not self._mdns_process:
            return
        self._mdns_process = None
        if getattr(result, "cancelled", False) or not getattr(result, "ok", False):
            return
        services = parse_mdns_services(result.stdout)
        if self._paired:
            service = find_service(services, CONNECT_SERVICE)
            if service is None:
                return
            if self._pairing_ip and not service.address.startswith(
                self._pairing_ip + ":"
            ):
                return
            if service.address in self._connect_attempts:
                return
            self._connect_attempts.add(service.address)
            self._start_connect(service)
            return
        service = find_service(services, PAIRING_SERVICE)
        if service is None or service.address == self._pairing_attempted:
            return
        self._pairing_attempted = service.address
        self._pairing_ip = service.address.rsplit(":", 1)[0]
        self._start_pair(service)

    def _start_pair(self, service) -> None:
        self._set_status(f"已发现设备 {service.address}，正在配对…")
        process = self.adb.run(
            None,
            "pair",
            service.address,
            self._password,
            timeout_ms=30000,
            record=False,
        )
        self._pair_process = process
        process.finished.connect(
            lambda result, p=process: self._on_pair_finished(p, result, service)
        )

    def _on_pair_finished(self, process, result, service) -> None:
        if process is not self._pair_process:
            return
        self._pair_process = None
        output = (
            getattr(result, "stdout", "") or getattr(result, "stderr", "")
        ).strip()
        if not getattr(result, "ok", False):
            self._set_status(f"配对失败：{output or '未知错误'}", error=True)
            self._poll_timer.stop()
            return
        self._paired = True
        self.address_label.setText(f"配对地址：{service.address}；正在自动连接…")
        self._set_status("配对成功，正在建立无线连接…")
        self._retry_timer.start(600)

    def _start_connect(self, service) -> None:
        self.address_label.setText(f"连接地址：{service.address}")
        self._set_status("正在连接设备…")
        process = self.adb.run(
            None,
            "connect",
            service.address,
            timeout_ms=20000,
            record=False,
        )
        self._connect_process = process
        process.finished.connect(
            lambda result, p=process: self._on_connect_finished(p, result, service)
        )

    def _on_connect_finished(self, process, result, service) -> None:
        if process is not self._connect_process:
            return
        self._connect_process = None
        output = (
            getattr(result, "stdout", "") or getattr(result, "stderr", "")
        ).strip()
        if not getattr(result, "ok", False):
            self._set_status(f"连接失败：{output or '未知错误'}", error=True)
            self._poll_timer.stop()
            return
        self._set_status(f"已连接：{output or service.address}")
        self._poll_timer.stop()
        self.paired.emit(service.address)
        self._close_timer.start(1200)

    def _cancel_processes(self) -> None:
        for attr in ("_mdns_process", "_pair_process", "_connect_process"):
            process = getattr(self, attr)
            setattr(self, attr, None)
            if process is not None and getattr(process, "is_running", False):
                process.cancel()

    def reject(self) -> None:
        self._poll_timer.stop()
        self._retry_timer.stop()
        self._close_timer.stop()
        self._cancel_processes()
        super().reject()

    def accept(self) -> None:
        self._poll_timer.stop()
        self._retry_timer.stop()
        self._close_timer.stop()
        self._cancel_processes()
        super().accept()


__all__ = ["WirelessQrDialog", "make_qr_pixmap"]
