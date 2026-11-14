from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class RiskLevel(str, Enum):
    HIGH = "高"
    CRITICAL = "极高"


@dataclass(frozen=True)
class DangerSpec:
    key: str
    title: str
    command: str
    impact: str
    risk: RiskLevel = RiskLevel.HIGH
    default_cancel: bool = True
    count: int | None = None
    detail: str = ""


def _spec(
    key: str,
    title: str,
    command: str,
    impact: str,
    risk: RiskLevel = RiskLevel.HIGH,
) -> DangerSpec:
    return DangerSpec(key=key, title=title, command=command, impact=impact, risk=risk)


DANGER_REGISTRY: dict[str, DangerSpec] = {
    "reboot.system": _spec(
        "reboot.system",
        "重启设备",
        "adb reboot",
        "设备将立即重启。当前终端、Logcat、视频连接会中断。",
        RiskLevel.HIGH,
    ),
    "reboot.bootloader": _spec(
        "reboot.bootloader",
        "重启到 Bootloader",
        "adb reboot bootloader",
        "设备将进入 Bootloader/Fastboot 模式，ADB 连接会中断。",
        RiskLevel.HIGH,
    ),
    "reboot.recovery": _spec(
        "reboot.recovery",
        "重启到 Recovery",
        "adb reboot recovery",
        "设备将进入 Recovery 模式，ADB 连接会中断。",
        RiskLevel.HIGH,
    ),
    "reboot.edl": _spec(
        "reboot.edl",
        "重启到 EDL",
        "adb reboot edl",
        "设备将尝试进入 EDL/9008 模式，仅部分机型支持；ADB 连接会中断。",
        RiskLevel.CRITICAL,
    ),
    "reboot.fastbootd": _spec(
        "reboot.fastbootd",
        "重启到 Fastbootd",
        "adb reboot fastboot",
        "设备将进入 Fastbootd 模式，ADB 连接会中断。",
        RiskLevel.HIGH,
    ),
    "device.tcpip": _spec(
        "device.tcpip",
        "切换为无线调试",
        "adb tcpip 5555",
        "设备 ADB 将切换到 TCP/IP 模式，当前 USB 连接可能断开。",
        RiskLevel.HIGH,
    ),
    "device.disconnect": _spec(
        "device.disconnect",
        "断开设备",
        "adb disconnect <序列号>",
        "当前无线设备的 ADB 连接将断开；USB 设备刷新后会自动恢复。",
        RiskLevel.HIGH,
    ),
    "app.clear_data": _spec(
        "app.clear_data",
        "清除应用数据",
        "pm clear <包名>",
        "应用的全部本地数据、登录状态和缓存会被清除，无法撤销。",
        RiskLevel.CRITICAL,
    ),
    "app.uninstall": _spec(
        "app.uninstall",
        "卸载应用",
        "pm uninstall <包名>",
        "应用会被卸载。系统应用可能影响系统功能，请确认可恢复。",
        RiskLevel.CRITICAL,
    ),
    "app.uninstall_keep_data": _spec(
        "app.uninstall_keep_data",
        "保留数据卸载",
        "pm uninstall -k <包名>",
        "应用会被卸载，但应用数据保留在设备上。",
        RiskLevel.HIGH,
    ),
    "app.batch_disable": _spec(
        "app.batch_disable",
        "批量禁用应用",
        "pm disable-user --user 0 <包名>",
        "所选应用会被冻结。系统应用或 Google 套件被禁用后可能影响系统功能。",
        RiskLevel.CRITICAL,
    ),
    "app.batch_disable_google": _spec(
        "app.batch_disable_google",
        "批量禁用 Google 套件",
        "pm disable-user --user 0 <包名>",
        "所选 Google 应用会被冻结，可能影响账号、推送、商店等依赖 Google 服务的功能。",
        RiskLevel.CRITICAL,
    ),
    "display.set_size": _spec(
        "display.set_size",
        "修改显示分辨率",
        "wm size <宽>x<高>",
        "设备显示分辨率会改变，界面可能暂时异常；不合适的数值可能导致黑屏。",
        RiskLevel.HIGH,
    ),
    "display.set_density": _spec(
        "display.set_density",
        "修改显示 DPI",
        "wm density <DPI>",
        "设备显示密度会改变，界面可能过大或过小；不合适的数值可能导致界面异常。",
        RiskLevel.HIGH,
    ),
    "settings.font_scale": _spec(
        "settings.font_scale",
        "修改字体大小",
        "settings put system font_scale <倍率>",
        "系统字体大小会改变，应用布局可能暂时异常。",
        RiskLevel.HIGH,
    ),
    "settings.animation": _spec(
        "settings.animation",
        "修改动画倍率",
        "settings put global <动画键> <倍率>",
        "窗口、过渡或属性动画速度会改变；设置为 0 会关闭对应动画。",
        RiskLevel.HIGH,
    ),
    "settings.write_global": _spec(
        "settings.write_global",
        "写入 Global 设置",
        "settings put global <键> <值>",
        "Global 设置会影响整台设备的行为，错误值可能导致系统功能异常。",
        RiskLevel.HIGH,
    ),
    "settings.write_secure": _spec(
        "settings.write_secure",
        "写入 Secure 设置",
        "settings put secure <键> <值>",
        "Secure 设置会影响系统界面和安全相关行为，错误值可能导致界面异常。",
        RiskLevel.HIGH,
    ),
    "settings.write_system": _spec(
        "settings.write_system",
        "写入 System 设置",
        "settings put system <键> <值>",
        "System 设置会影响系统行为，错误值可能导致界面或功能异常。",
        RiskLevel.HIGH,
    ),
    "battery.simulate": _spec(
        "battery.simulate",
        "模拟电池状态",
        "dumpsys battery set <字段> <值>",
        "设备会显示模拟的电池数据，可能影响电量显示和充电判断；重启后失效。",
        RiskLevel.HIGH,
    ),
    "flash.unlock": _spec(
        "flash.unlock",
        "解锁 Bootloader",
        "adb shell oem unlock",
        "仅适用于支持 OEM 解锁的机型。解锁可能清除数据并使设备失去保修。",
        RiskLevel.CRITICAL,
    ),
    "flash.lock": _spec(
        "flash.lock",
        "回锁 Bootloader",
        "adb shell oem lock",
        "仅适用于支持 OEM 回锁的机型。回锁可能导致设备无法启动或数据丢失。",
        RiskLevel.CRITICAL,
    ),
    "flash.flash_partition": _spec(
        "flash.flash_partition",
        "向分区刷入镜像",
        "fastboot flash <分区> <镜像>",
        "向设备分区写入镜像。错误的镜像或分区会导致设备无法启动。",
        RiskLevel.CRITICAL,
    ),
    "flash.reboot_fastboot": _spec(
        "flash.reboot_fastboot",
        "重启到 Fastboot",
        "adb reboot bootloader",
        "设备将进入 Fastboot 模式，ADB 连接会中断。",
        RiskLevel.HIGH,
    ),
    "flash.reboot_recovery": _spec(
        "flash.reboot_recovery",
        "重启到 Recovery",
        "adb reboot recovery",
        "设备将进入 Recovery 模式，ADB 连接会中断。",
        RiskLevel.HIGH,
    ),
    "flash.reboot_edl": _spec(
        "flash.reboot_edl",
        "重启到 EDL",
        "adb reboot edl",
        "设备将尝试进入 EDL/9008 模式，仅部分机型支持；ADB 连接会中断。",
        RiskLevel.CRITICAL,
    ),
    "files.push_system": _spec(
        "files.push_system",
        "向系统分区推送文件",
        "adb push <本地文件> <系统分区路径>",
        "向只读或系统分区写入文件，可能导致设备无法启动；通常需要 root/remount。",
        RiskLevel.CRITICAL,
    ),
    "script.run": _spec(
        "script.run",
        "运行脚本",
        "按脚本逐行执行 adb 命令",
        "脚本中的 ADB 命令会作用于当前设备。请先检查卸载、清数据、重启等操作。",
        RiskLevel.HIGH,
    ),
    "snapshot.rollback": _spec(
        "snapshot.rollback",
        "回滚设备配置",
        "逐项执行快照中记录的写入命令",
        "将按快照恢复所选设置。部分设置可能需要重启才能生效。",
        RiskLevel.HIGH,
    ),
}


def get_danger(
    key: str,
    command: str | None = None,
    count: int | None = None,
    detail: str | None = None,
) -> DangerSpec:
    try:
        spec = DANGER_REGISTRY[key]
    except KeyError as exc:
        raise KeyError(f"未登记的危险操作: {key}") from exc
    return replace(
        spec,
        command=command if command is not None else spec.command,
        count=count,
        detail=detail if detail is not None else spec.detail,
    )
